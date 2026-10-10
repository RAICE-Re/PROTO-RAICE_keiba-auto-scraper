import pandas as pd
import requests
from io import StringIO
import re
from datetime import datetime
import pytz
import time

jst = pytz.timezone('Asia/Tokyo')
today = datetime.now(jst)
today_str = today.strftime('%Y-%m-%d')
current_time = today.strftime('%H:%M')

# 今日の日付（例: 10月10日）
today_str_jp = f"{today.month}月{today.day}日"

print(f"【実行日時】 {today_str} {current_time} (JST)")
print("本日の開催競馬場をYahoo!競馬から自動検索中...\n")

url_top = "https://sports.yahoo.co.jp/keiba/"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

res_top = requests.get(url_top, headers=headers)

# 1. ページ内に隠れているすべての「レースID候補」を抽出
base_ids = set()
links = re.findall(r'href="([^"]+)"', res_top.text)
for link in links:
    match = re.search(r'/keiba/race/[^/]+/(\d{8,10})', link)
    if match:
        base_ids.add(match.group(1)[:8])

place_dict = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
    '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'
}

today_bases = {}

if base_ids:
    print(f"開催日の候補を {len(base_ids)} 件発見。本日のレースを厳密に特定します...")
    for b_id in base_ids:
        place_code = b_id[2:4]
        if place_code in place_dict:
            check_url = f"https://sports.yahoo.co.jp/keiba/race/list/{b_id}/"
            res_check = requests.get(check_url, headers=headers)
            
            # 修正ポイント：ページ全体ではなく、<title>タグ（ページタイトル）に今日の日付があるかだけをチェック
            title_match = re.search(r'<title>(.*?)</title>', res_check.text)
            if title_match and today_str_jp in title_match.group(1):
                today_bases[place_dict[place_code]] = b_id

if today_bases:
    print("\n✅ 以下の開催地を完全に特定しました。データ抽出を開始します。\n")
    for place, base_id in today_bases.items():
        print(f"--- 【{place}競馬場】 ---")
        all_races = []
        
        for race_no in range(1, 13):
            race_id = f"{base_id}{race_no:02d}"
            url = f"https://sports.yahoo.co.jp/keiba/race/odds/tfw/{race_id}/"
            
            try:
                res = requests.get(url, headers=headers)
                if res.status_code != 200:
                    continue
                    
                tables = pd.read_html(StringIO(res.text))
                if not tables:
                    continue
                    
                df = tables[0]
                
                if '単勝' in df.columns and '馬名' in df.columns:
                    horse_names = df['馬名']
                    odds = df['単勝'].astype(str).replace('-', '')
                elif '馬名性齢/毛色' in df.columns and '人気(オッズ)' in df.columns:
                    horse_names = df['馬名性齢/毛色'].apply(lambda x: str(x).split()[0] if pd.notnull(x) else "")
                    odds = df['人気(オッズ)'].astype(str).str.extract(r'\(([\d.]+)\)')[0]
                else:
                    continue
                
                formatted_df = pd.DataFrame({
                    'game_id': f"{today_str.replace('-', '')}-{place}-{race_no}",
                    'date': today_str,
                    'time': current_time,
                    'place': place,
                    'race_no': race_no,
                    'horse_no': df['馬番'],
                    'horse_name': horse_names,
                    'odds': odds
                })
                
                all_races.append(formatted_df)
                print(f" {race_no}R 完了 |", end="")
                
            except Exception as e:
                print(f"\n ⚠ {race_no}R エラー", end="")
                
            time.sleep(1)
            
        if all_races:
            final_csv = pd.concat(all_races, ignore_index=True)
            file_name = f"{today_str.replace('-', '')}_{place}_{current_time.replace(':', '')}_odds.csv"
            final_csv.to_csv(file_name, index=False, encoding='utf-8-sig')
            print(f"\n 💾 '{file_name}' 保存完了！\n")
        
else:
    print("⚠ 本日のレースIDが見つかりませんでした。")
