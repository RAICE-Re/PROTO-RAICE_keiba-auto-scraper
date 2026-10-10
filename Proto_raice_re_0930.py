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
today_str_jp = f"{today.month}月{today.day}日"

print(f"【実行日時】 {today_str} {current_time} (JST)")
print("PROTO-RAICE Re 用のリッチデータセット（出馬表×オッズ結合）を抽出します...\n")

url_top = "https://sports.yahoo.co.jp/keiba/"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

res_top = requests.get(url_top, headers=headers)
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
    for b_id in base_ids:
        place_code = b_id[2:4]
        if place_code in place_dict:
            check_url = f"https://sports.yahoo.co.jp/keiba/race/list/{b_id}/"
            res_check = requests.get(check_url, headers=headers)
            title_match = re.search(r'<title>(.*?)</title>', res_check.text)
            if title_match and today_str_jp in title_match.group(1):
                today_bases[place_dict[place_code]] = b_id

# データ分割用の関数群
def parse_horse_info(x):
    try:
        parts = str(x).split()
        name = parts[0]
        if len(parts) > 1:
            info = parts[1].split('/')
            sex_age = info[0]
            sex = sex_age[0] if len(sex_age) > 0 else ""
            age = sex_age[1:] if len(sex_age) > 1 else ""
            color = info[1] if len(info) > 1 else ""
        else:
            sex, age, color = "", "", ""
        return pd.Series([name, sex, age, color])
    except:
        return pd.Series(["", "", "", ""])

def parse_jockey_weight(x):
    match = re.search(r'(.+?)(\d+(\.\d+)?)$', str(x))
    if match:
        return pd.Series([match.group(1).strip(), match.group(2)])
    return pd.Series([x, ""])

def parse_trainer(x):
    match = re.search(r'(.+?)\((.+)\)', str(x))
    if match:
        return pd.Series([match.group(1).strip(), match.group(2)])
    return pd.Series([x, ""])

if today_bases:
    print("✅ 以下の開催地を特定しました。データ抽出を開始します。\n")
    for place, base_id in today_bases.items():
        print(f"--- 【{place}競馬場】 ---")
        all_races = []
        
        for race_no in range(1, 13):
            race_id = f"{base_id}{race_no:02d}"
            denma_url = f"https://sports.yahoo.co.jp/keiba/race/denma/{race_id}/"
            odds_url = f"https://sports.yahoo.co.jp/keiba/race/odds/tfw/{race_id}/"
            
            try:
                # 1. 出馬表（denma）から基本情報を取得
                res_denma = requests.get(denma_url, headers=headers)
                if res_denma.status_code != 200:
                    continue
                df_denma = pd.read_html(StringIO(res_denma.text))[0]
                
                horse_info = df_denma['馬名性齢/毛色'].apply(parse_horse_info)
                jockey_info = df_denma['騎手名斤量'].apply(parse_jockey_weight)
                trainer_info = df_denma['調教師名(所属)'].apply(parse_trainer)
                
                denma_clean = pd.DataFrame({
                    'horse_no': df_denma['馬番'],
                    'bracket_no': df_denma['枠番'],
                    'horse_name': horse_info[0],
                    'sex': horse_info[1],
                    'age': horse_info[2],
                    'hair_color': horse_info[3],
                    'jockey': jockey_info[0],
                    'weight': jockey_info[1],
                    'trainer': trainer_info[0],
                    'affiliation': trainer_info[1]
                })
                
                # 2. オッズ表（odds）から最新オッズだけを取得
                res_odds = requests.get(odds_url, headers=headers)
                df_odds = pd.read_html(StringIO(res_odds.text))[0]
                
                if '単勝' in df_odds.columns:
                    odds_val = df_odds['単勝'].astype(str).replace('-', '')
                elif '人気(オッズ)' in df_odds.columns:
                    odds_val = df_odds['人気(オッズ)'].astype(str).str.extract(r'\(([\d.]+)\)')[0]
                else:
                    odds_val = ""
                    
                odds_clean = pd.DataFrame({
                    'horse_no': df_odds['馬番'],
                    'odds': odds_val
                })
                
                # 3. 馬番をキーにして安全にマージ（結合）
                merged_df = pd.merge(denma_clean, odds_clean, on='horse_no', how='left')
                
                # 最終フォーマットに整形
                formatted_df = pd.DataFrame({
                    'game_id': f"{today_str.replace('-', '')}-{place}-{race_no}",
                    'date': today_str,
                    'time': current_time,
                    'place': place,
                    'race_no': race_no,
                    'bracket_no': merged_df['bracket_no'],
                    'horse_no': merged_df['horse_no'],
                    'horse_name': merged_df['horse_name'],
                    'sex': merged_df['sex'],
                    'age': merged_df['age'],
                    'hair_color': merged_df['hair_color'],
                    'jockey': merged_df['jockey'],
                    'weight': merged_df['weight'],
                    'trainer': merged_df['trainer'],
                    'affiliation': merged_df['affiliation'],
                    'odds': merged_df['odds']
                })
                
                all_races.append(formatted_df)
                print(f" {race_no}R 完了 |", end="")
                
            except Exception as e:
                print(f"\n ⚠ {race_no}R エラー", end="")
                
            time.sleep(1)
            
        if all_races:
            final_csv = pd.concat(all_races, ignore_index=True)
            file_name = f"{today_str.replace('-', '')}_{place}_{current_time.replace(':', '')}_Re_odds.csv"
            final_csv.to_csv(file_name, index=False, encoding='utf-8-sig')
            print(f"\n 💾 '{file_name}' 保存完了！\n")
else:
    print("⚠ 本日のレースIDが見つかりませんでした。")
