import sys
import requests
import datetime
import time
import json
from cachetools import TTLCache

# 使用 1 小時 TTL 快取機制，避免頻繁請求氣象署 API
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

# 1. 將氣象署 Wx 天氣代碼對應至 OWM 代碼，讓 iOS 6 正常顯示天氣圖示
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


# 2. 核心功能：直接向中央氣象署拉取資料並翻譯
def getWeather(woeid):
    # 如果快取裡有，直接回傳
    if woeid in woeidCache:
        return woeidCache[woeid]

    # 直接使用你測試成功的完整網址
    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization=CWB-68CB4AF6-A1EF-47C8-9614-1A6BFB80D6C8&format=JSON&elementName="
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    try:
        req_response = requests.get(url, headers=headers, timeout=10)
        req_response.raise_for_status() 
        response = req_response.json()
        
        # 預設抓取回傳結果中的第一個城市（一般為台北市/基隆市等順序）
        weather_data = response['records']['location'][0]
        elements = weather_data['weatherElement']
        
        # 提取所需的天氣要素
        wx = next(el for el in elements if el['elementName'] == 'Wx')['time']
        min_t = next(el for el in elements if el['elementName'] == 'MinT')['time']
        max_t = next(el for el in elements if el['elementName'] == 'MaxT')['time']
        pop = next(el for el in elements if el['elementName'] == 'PoP')['time']

        current_min = float(min_t[0]['parameter']['parameterName'])
        current_max = float(max_t[0]['parameter']['parameterName'])
        current_temp = round((current_min + current_max) / 2)

        # 封裝成 iOS 6 (WeatherX 插件) 看得懂的 OWM 1.0 JSON 規格
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

        # 存入快取
        woeidCache[woeid] = spoofedOwmResponse
        return spoofedOwmResponse

    except Exception as e:
        print("Fetch weather failed: ", e)
        return None


# ==========================================
# Netlify Functions 專用進入點 (Handler)
# ==========================================
def handler(event, context):
    query_params = event.get("queryStringParameters", {}) or {}
    woeid = query_params.get("woeid", "default_woeid")

    # 獲取並轉譯後的氣象資料
    weather_data = getWeather(woeid)

    if weather_data is None:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*"
            },
            "body": json.dumps({"error": "Failed to fetch weather from CWA"})
        }

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*"
        },
        "body": json.dumps(weather_data)
    }