import sys
import requests
import datetime
import time
import json
from cachetools import TTLCache

# OWM API Key 保持相容
owmkey = sys.argv[1] if len(sys.argv) > 1 else None

# 使用 1 小時 TTL 快取機制
woeidCache = TTLCache(maxsize=100, ttl=3600)

dateTable = {
  0: 1,
  1: 2,
  2: 3,
  3: 4,
  4: 5,
  5: 6,
  6: 7
}

# Helper Functions

def getLatLongForQ(q):
    latIndex1 = q.index('lat=')+4
    latIndex2 = q.index(' and')
    longIndex1 = q.index('lon=')+4
    longIndex2 = q.index(' and', latIndex2+3)
    lat = q[latIndex1:latIndex2]
    long = q[longIndex1:longIndex2-1]
    print("lat = " + lat)
    print("long = " + long)
    print("longIndex1 = " + q)
    return [lat, long]


# 1. 將氣象署 Wx 天氣代碼對應至 OWM 代碼[cite: 1]
def mapCwaWxToOwmId(wxCode):
    try:
        code = int(wxCode)
    except Exception:
        return 800
    if code == 1: return 800        # 晴天 -> Clear
    if 2 <= code <= 3: return 801   # 多雲時晴 -> Few clouds
    if 4 <= code <= 7: return 803   # 陰天 / 多雲 -> Broken/Overcast clouds
    if 8 <= code <= 22: return 500  # 雨天 -> Rain
    if code >= 23: return 211       # 雷雨 -> Thunderstorm
    return 800


# 2. 直接讀取你指定的完整氣象署 API 網址並進行轉換[cite: 1]
def getWeather(woeid):
    # 快取機制
    if woeid in woeidCache:
        print("Returning cached response")
        return woeidCache[woeid]

    # 【核心修改】直接讀取你提供、100% 測試可用的完整 API 網址
    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization=CWB-68CB4AF6-A1EF-47C8-9614-1A6BFB80D6C8&format=JSON&elementName="
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    try:
        req_response = requests.get(url, headers=headers, timeout=10)
        req_response.raise_for_status() 
        response = req_response.json()
        
        # 預設直接抓取回傳結果中的第一個縣市（通常是第一個被排序的縣市）
        weather_data = response['records']['location'][0]
        elements = weather_data['weatherElement']
        
        wx = next(el for el in elements if el['elementName'] == 'Wx')['time']
        min_t = next(el for el in elements if el['elementName'] == 'MinT')['time']
        max_t = next(el for el in elements if el['elementName'] == 'MaxT')['time']
        pop = next(el for el in elements if el['elementName'] == 'PoP')['time']

        current_min = float(min_t[0]['parameter']['parameterName'])
        current_max = float(max_t[0]['parameter']['parameterName'])
        current_temp = round((current_min + current_max) / 2)

        # 封裝成 OWM 1.0 JSON 規格
        spoofedOwmResponse = {
            "timezone_offset": 28800,
            "current": {
                "dt": int(datetime.datetime.now().timestamp()),
                "temp": current_temp,
                "pressure": 1013,
                "humidity": 75,
                "dew_point": 18,
                "feels_like": current_temp,
                "visibility": 10000,
                "wind_speed": 3.5,
                "wind_deg": 90,
                "sunrise": int(datetime.datetime.now().replace(hour=6, minute=0, second=0).timestamp()),
                "sunset": int(datetime.datetime.now().replace(hour=18, minute=0, second=0).timestamp()),
                "weather": [
                    {
                        "id": mapCwaWxToOwmId(wx[0]['parameter']['parameterValue']),
                        "description": wx[0]['parameter']['parameterName']
                    }
                ]
            },
            "daily": [
                {
                    "pop": float(pop[0]['parameter']['parameterName']) / 100,
                    "temp": {
                        "min": float(min_t[0]['parameter']['parameterName']),
                        "max": float(max_t[0]['parameter']['parameterName'])
                    },
                    "weather": [
                        { "id": mapCwaWxToOwmId(wx[0]['parameter']['parameterValue']) }
                    ]
                },
                {
                    "pop": float(pop[1]['parameter']['parameterName']) / 100,
                    "temp": {
                        "min": float(min_t[1]['parameter']['parameterName']),
                        "max": float(max_t[1]['parameter']['parameterName'])
                    },
                    "weather": [
                        { "id": mapCwaWxToOwmId(wx[1]['parameter']['parameterValue']) }
                    ]
                },
                {
                    "pop": float(pop[2]['parameter']['parameterName']) / 100,
                    "temp": {
                        "min": float(min_t[2]['parameter']['parameterName']),
                        "max": float(max_t[2]['parameter']['parameterName'])
                    },
                    "weather": [
                        { "id": mapCwaWxToOwmId(wx[2]['parameter']['parameterValue']) }
                    ]
                }
            ],
            "hourly": []
        }

        # 寫入快取
        woeidCache[woeid] = spoofedOwmResponse
        return spoofedOwmResponse

    except Exception as e:
        print("Fetch weather failed: ", e)
        return None

  
def dayOrNight(timestamp):
    global global_sunrise_time, global_sunset_time
    if global_sunrise_time is None or global_sunset_time is None:
        return False
    return global_sunrise_time < timestamp < global_sunset_time


def weatherIcon(id, sunset, timestamp=None):
    day = True if timestamp is None else dayOrNight(timestamp)
    id = str(id)
    if id.startswith("2"): return 0
    if id.startswith("3"): return 9
    if id.startswith("5"):
        if id == "500": return 39 if day else 9
        if id == "501": return 11
        if id in ["502", "503", "504"]: return 11
        if id == "511": return 25
        if id.startswith("52"): return 11
    if id.startswith("6"):
        if id in ["600", "620"]: return 13
        if id in ["601", "621"]: return 15
        if id in ["602", "622"]: return 46
        if id in ["611", "612", "613"]: return 6
        if id == "615" or id == "616": return 35
    if id.startswith("7"):
        if id == "781": return 0
        return 23
    if id.startswith("8"):
        if id == "800": return 32 if day else 31
        if id == "801": return 30 if day else 29
        if id == "802": return 30 if day else 29
        if id == "803" or id == "804": return 27
    if id.startswith("9"):
        if id == "900" or id == "901" or id == "902" or id == "962": return 0
        if id == "903": return 25
        if id == "904": return 19
        if id == "905": return 23
        if id == "906": return 17
    return 48

def weatherPoP(pop):
  return int(float(pop)*100)

def hourNext(n, currTime, timezone_offset):
  hourTime = time.gmtime(currTime+timezone_offset+(3600*n))
  return "%s:00" % str(hourTime.tm_hour)

def weatherDate(dt, timezone_offset):
  currTime = time.gmtime(dt+timezone_offset)
  return f"{str(currTime.tm_hour)}:{str(currTime.tm_min)}"

def weatherSunrise(sunrise, timezone_offset):
    global global_sunrise_time
    global_sunrise_time = sunrise + timezone_offset
    hourTime = time.gmtime(global_sunrise_time)
    return f"{str(hourTime.tm_hour)}:{str(hourTime.tm_min)}"

def weatherSunset(sunset, timezone_offset):
    global global_sunset_time
    global_sunset_time = sunset + timezone_offset
    hourTime = time.gmtime(global_sunset_time)
    return f"{str(hourTime.tm_hour)}:{str(hourTime.tm_min)}"

def dayNext(n):
  return dateTable[(datetime.datetime.now() + datetime.timedelta(days=(n))).weekday()]

def dayArray():
  return [
    dayNext(1), dayNext(2), dayNext(3), dayNext(4), dayNext(5), dayNext(6)
  ]


# ==========================================
# Netlify Functions 專用進入點 (Handler)
# ==========================================
def handler(event, context):
    query_params = event.get("queryStringParameters", {}) or {}
    woeid = query_params.get("woeid", "default_woeid")

    # 獲取氣象資料（不再需要傳入 lat, lon 與 api_key，後端直接向指定 API 拿資料）
    weather_data = getWeather(woeid)

    if weather_data is None:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({"error": "Failed to fetch weather from CWA"})
        }

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(weather_data)
    }