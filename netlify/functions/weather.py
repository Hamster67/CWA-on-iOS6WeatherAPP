import sys
import requests
import datetime
import time
from cachetools import TTLCache

# OWM API Key 保持相容
owmkey = sys.argv[1] if len(sys.argv) > 1 else None

# 使用 1 小時 TTL 快取機制[cite: 2]
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


# 1. 簡易座標轉換台灣縣市
def getCountyByCoordinates(lat, lon):
    try:
        latitude = float(lat)
        longitude = float(lon)
    except Exception:
        return '臺北市'

    if latitude > 25.0:
        if longitude < 121.4: return '新北市'
        return '臺北市'
    elif latitude > 24.5:
        if longitude < 121.0: return '桃園市'
        return '新竹縣'
    elif latitude > 24.0:
        return '臺中市'
    elif latitude > 23.5:
        return '彰化縣'
    elif latitude > 23.0:
        if longitude > 121.0: return '臺東縣'
        return '臺南市'
    elif latitude > 22.0:
        return '高雄市'
    return '臺北市'


# 2. 將氣象署 Wx 天氣代碼對應至 OWM 代碼[cite: 1]
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


# 3. 直接對接氣象署 API 取得預報，並轉換為 OWM 格式，支援自訂金鑰[cite: 1, 2]
def getWeather(lat, lng, woeid, custom_api_key=None):
    # 【修改重點 1】若有傳入自訂金鑰，將快取 Key 與金鑰綁定（例如: "123456_CWA-XXX..."）
    # 避免不同使用者在相同地區（同 woeid）時，因為快取導致拿到別人的請求結果或權限出錯。
    cache_key = f"{woeid}_{custom_api_key}" if custom_api_key else woeid

    # 快取機制
    if cache_key in woeidCache:
        print("Returning cached response")
        return woeidCache[cache_key]

    # 【修改重點 2】優先選用網址傳遞過來的自訂 API 授權碼，沒有的話才 fallback 到預設值
    CWA_API_KEY = custom_api_key if custom_api_key else "CWA-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    county = getCountyByCoordinates(lat, lng)

    # 呼叫氣象署「一般天氣預報-今明36小時天氣預報」API
    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
    params = {
        "Authorization": CWA_API_KEY,
        "locationName": county,
        "elementName": "Wx,MinT,MaxT,PoP"
    }

    try:
        response = requests.get(url, params=params, timeout=10).json()
        weather_data = response['records']['location'][0]
        elements = weather_data['weatherElement']
        
        # 解析氣象元素
        wx = next(el for el in elements if el['elementName'] == 'Wx')['time']
        min_t = next(el for el in elements if el['elementName'] == 'MinT')['time']
        max_t = next(el for el in elements if el['elementName'] == 'MaxT')['time']
        pop = next(el for el in elements if el['elementName'] == 'PoP')['time']

        # 當前氣溫預估 (取今天最高溫與最低溫平均值)
        current_min = float(min_t[0]['parameter']['parameterName'])
        current_max = float(max_t[0]['parameter']['parameterName'])
        current_temp = round((current_min + current_max) / 2)

        # 封裝成 OWM 1.0 JSON 規格[cite: 2]
        spoofedOwmResponse = {
            "timezone_offset": 28800,  # 台北標準時區 (UTC+8)
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
                # 今天 (第一段預報)
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
                # 明天 (第二段預報)
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
                # 後天 (第三段預報)
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
            "hourly": []  # 保持空陣列
        }

        # 寫入 TTLCache 機制，使用綁定金鑰的 cache_key
        woeidCache[cache_key] = spoofedOwmResponse
        return spoofedOwmResponse

    except Exception as e:
        print("Fetch weather from CWA API failed: ", e)
        return None

  
def dayOrNight(timestamp):
    global global_sunrise_time, global_sunset_time
    if global_sunrise_time is None or global_sunset_time is None:
        print("Global sunrise or sunset time has not been set.")
        return False
    
    if global_sunrise_time < timestamp < global_sunset_time:
        return True
    else:
        return False


def weatherIcon(id, sunset, timestamp=None):
    day = True if timestamp is None else dayOrNight(timestamp)
    id = str(id)
    if id.startswith("2"):
        return 0
    if id.startswith("3"):
        return 9
    if id.startswith("5"):
        if id == "500":
            return 39 if day else 9
        if id == "501":
            return 11
        if id in ["502", "503", "504"]:
            return 11
        if id == "511":
            return 25
        if id.startswith("52"):
            return 11
    if id.startswith("6"):
        if id in ["600", "620"]:
            return 13
        if id in ["601", "621"]:
            return 15
        if id in ["602", "622"]:
            return 46
        if id in ["611", "612", "613"]:
            return 6
        if id == "615" or id == "616":
            return 35
    if id.startswith("7"):
        if id == "781":
            return 0
        return 23
    if id.startswith("8"):
        if id == "800":
            return 32 if day else 31
        if id == "801":
            return 30 if day else 29
        if id == "802":
            return 30 if day else 29
        if id == "803" or id == "804":
            return 27
    if id.startswith("9"):
        if id == "900" or id == "901" or id == "902" or id == "962":
            return 0
        if id == "903":
            return 25
        if id == "904":
            return 19
        if id == "905":
            return 23
        if id == "906":
            return 17
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
    dayNext(1),
    dayNext(2),
    dayNext(3),
    dayNext(4),
    dayNext(5),
    dayNext(6)
  ]

def moonPhase(phase):
  if phase == 0 or phase == 1:
    return [0, 0]
  elif phase == 0.25:
    return [64, 1]
  elif phase == 0.5:
    return [108, 5]
  elif phase == 0.75:
    return [47, 5]
  elif 0.75 <= phase <= 1:
    return [16, 5]
  elif 0.50 <= phase <= 0.75:
    return [72, 5]
  elif 0.25 <= phase <= 0.50:
    return [84, 1]
  elif 0 <= phase <= 0.25:
    return [32, 1]