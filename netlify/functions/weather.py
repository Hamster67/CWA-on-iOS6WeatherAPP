import sys
import requests
import datetime
import time
from cachetools import TTLCache

# 如果你不需要 OWM API Key 了，可以自行決定是否保留
owmkey = sys.argv[1] if len(sys.argv) > 1 else None

# 使用你原本設定的 1 小時 TTL 快取機制
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


# 1. 簡易座標轉換台灣縣市 (氣象署 API 需要中文縣市名稱進行篩選)
def getCountyByCoordinates(lat, lon):
    try:
        latitude = float(lat)
        longitude = float(lon)
    except Exception:
        return '臺北市'

    # 粗略台灣緯度邊界判定，適合快速定位
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


# 2. 將氣象署 Wx 天氣代碼對應至 OWM 代碼 (確保 iOS 6 能顯示對應的天氣圖示)[cite: 1]
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


# 3. 直接對接氣象署 API 取得預報，並轉換為 OWM 格式[cite: 1, 2]
def getWeather(lat, lng, woeid):
    # 快取機制，防止高頻率重複請求 CWA
    if woeid in woeidCache:
        print("Returning cached response")
        return woeidCache[woeid]

    # TODO: 請在此處填入你在「中央氣象署開放資料平台」免費申請的 API 授權碼
    CWA_API_KEY = "CWA-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
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

        # 封裝成 OWM 1.0 JSON 規格，以利 XMLGenerator 讀取[cite: 2]
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
            "hourly": []  # 保持空陣列，iOS 6 在沒有每小時數據時依然能正常顯示大圖與日預報
        }

        # 寫入 TTLCache 機制
        woeidCache[woeid] = spoofedOwmResponse
        return spoofedOwmResponse

    except Exception as e:
        print("Fetch weather from CWA API failed: ", e)
        return None

  
def dayOrNight(timestamp):
    global global_sunrise_time, global_sunset_time

    # Check if the global sunrise and sunset times have been set
    if global_sunrise_time is None or global_sunset_time is None:
        print("Global sunrise or sunset time has not been set.")
        return False  # Or handle the error as you see fit
    
    print("Forecast time (epoch):", timestamp)
    print("Sunrise time (epoch):", global_sunrise_time)
    print("Sunset time (epoch):", global_sunset_time)

    if global_sunrise_time < timestamp < global_sunset_time:
        print("DAYTIME for the forecast")
        return True
    else:
        print("NIGHTTIME for the forecast")
        return False


def weatherIcon(id, sunset, timestamp=None):  # timestamp is optional now
    day = True if timestamp is None else dayOrNight(timestamp)
    id = str(id)
    if id.startswith("2"):  # Thunderstorm
        return 0  # Lightning
    if id.startswith("3"):  # Drizzle
        return 9
    if id.startswith("5"):  # Rain
        if id == "500":  # Light rain
            return 39 if day else 9
        if id == "501":  # Moderate rain
            return 11
        if id in ["502", "503", "504"]:  # Heavy intensity rain
            return 11
        if id == "511":  # Freezing rain
            return 25
        if id.startswith("52"):  # Shower rain
            return 11
    if id.startswith("6"):  # Snow
        if id in ["600", "620"]:  # Light snow
            return 13
        if id in ["601", "621"]:  # Snow
            return 15
        if id in ["602", "622"]:  # Heavy snow
            return 46
        if id in ["611", "612", "613"]:  # Sleet
            return 6
        if id == "615" or id == "616":  # Rain and snow
            return 35
    if id.startswith("7"):  # Atmosphere (Mist, Smoke, Haze, etc.)
        if id == "781":  # Tornado
            return 0  # No specific icon for tornado, using lightning
        return 23  # Use the same icon for all misty conditions
    if id.startswith("8"):  # Clear and clouds
        if id == "800":  # Clear sky
            return 32 if day else 31
        if id == "801":  # Few clouds
            return 30 if day else 29
        if id == "802":  # Scattered clouds
            return 30 if day else 29
        if id == "803" or id == "804":  # Broken clouds, overcast clouds
            return 27
    if id.startswith("9"):  # Extreme
        if id == "900" or id == "901" or id == "902" or id == "962":  # Tornado + hurricanes
            return 0
        if id == "903":  # Cold
            return 25
        if id == "904":  # Hot
            return 19
        if id == "905":  # Windy
            return 23
        if id == "906":  # Hail
            return 17
    return 48  # Default 'unknown' code

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