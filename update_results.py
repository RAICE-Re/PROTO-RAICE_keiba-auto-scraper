import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import os
import re
from datetime import datetime, timedelta
import pytz

# ==========================================
# 1. 既存の master_results.csv を読み込み
# ==========================================
master_file = 'master_results.csv'
existing_ids = set()

if os.path.exists(master_file):
    df_existing = pd.read_csv(master_file, dtype={'Winning_Numbers': str})
    if 'game_id' in df_existing.columns:
        existing_ids = set(df_existing['game_id'].astype(str))
else:
    df_existing = pd.DataFrame(columns=['game_id', 'date', 'place', 'race_no', 'Winning_Numbers', 'Points'])

print(f"📂 既存データ数: {len(existing_ids)} レース")

# ==========================================
# 2. Yahoo!競馬から未取得の最新結果を取得
# ==========================================
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
place_dict = {'01':'札幌', '02':'函館', '03':'福島', '04':'新潟', '05':'東京', '06':'中山', '07':'中京', '08':'京都', '09':'阪神', '10':'小倉'}
place_order = ['札幌', '函館', '福島', '新潟', '東京', '中山', '中京', '京都', '阪神', '小倉']

jst = pytz.timezone('Asia/Tokyo')
today = datetime.now(jst)

# 当月（月初7日以内なら前月も含める）を対象にする
target_months = [(str(today.year), f"{today.month:02d}")]
if today.day <= 7:
    prev_month_date = today.replace(day=1) - timedelta(days=1)
    target_months.insert(0, (str(prev_month_date.year), f"{prev_month_date.month:02d}"))

# 過去14日以内のレースのみチェック（無駄なアクセス防止）
cutoff_date = (today - timedelta(days=14)).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

all_new_results = []

for year, month in target_months:
    url_month = f"https://sports.yahoo.co.jp/keiba/schedule/monthly?year={year}&month={month}"
    res_month = requests.get(url_month, headers=headers)
    base_ids = set(re.findall(r'/keiba/race/list/(\d{8})', res_month.text))
    
    for b_id in base_ids:
        url_list = f"https://sports.yahoo.co.jp/keiba/race/list/{b_id}"
        res_list = requests.get(url_list, headers=headers)
        soup_list = BeautifulSoup(res_list.content, 'html.parser')
        
        # 開催日を確認して対象外の日付は丸ごとスキップ
        list_date_match = re.search(rf'{year}年(\d{{1,2}})月(\d{{1,2}})日', soup_list.get_text())
        if list_date_match:
            m = int(list_date_match.group(1))
            d = int(list_date_match.group(2))
            check_date = f"{year}-{m:02d}-{d:02d}"
            if check_date < cutoff_date or check_date > today_str:
                continue
        
        race_ids = set(re.findall(r'/keiba/race/[^/]+/(\d{10})', res_list.text))
        
        for r_id in race_ids:
            place_code = r_id[2:4]
            place = place_dict.get(place_code, "不明")
            race_no = int(r_id[8:10])
            
            # 事前にgame_idが分かる場合は重複スキップ
            if list_date_match:
                pre_game_id = f"{check_date.replace('-', '')}-{place}-{race_no}"
                if pre_game_id in existing_ids:
                    continue

            try:
                url_result = f"https://sports.yahoo.co.jp/keiba/race/result/{r_id}/"
                res_race = requests.get(url_result, headers=headers)
                soup = BeautifulSoup(res_race.content, 'html.parser')
                page_text = soup.get_text()
                
                date_match = re.search(rf'{year}年(\d{{1,2}})月(\d{{1,2}})日', page_text)
                if not date_match:
                    continue
                m = int(date_match.group(1))
                d = int(date_match.group(2))
                date_str = f"{year}-{m:02d}-{d:02d}"
                
                if date_str < cutoff_date or date_str > today_str:
                    continue
                
                game_id = f"{date_str.replace('-', '')}-{place}-{race_no}"
                if game_id in existing_ids:
                    continue

                # 3連複・3連単の抽出
                winning_numbers = ""
                points = 0
                
                for tr in soup.find_all('tr'):
                    tds = tr.find_all(['th', 'td'])
                    if not tds:
                        continue
                    header_text = tds[0].get_text(strip=True)
                    
                    if '3連複' in header_text and len(tds) >= 3:
                        raw_nums = tds[1].get_text(strip=True).replace(' ', '').replace('－', '-')
                        nums = re.split(r'[-ー]', raw_nums)
                        if len(nums) == 3:
                            winning_numbers = "-".join(sorted(nums, key=int))
                            
                    if '3連単' in header_text and len(tds) >= 3:
                        payout_str = tds[2].get_text(strip=True).replace(',', '').replace('円', '')
                        for p_num in re.findall(r'\d+', payout_str):
                            p = int(p_num)
                            if p >= 100 and p > points:
                                points = p

                if winning_numbers != "" and points > 0:
                    all_new_results.append({
                        'game_id': game_id,
                        'date': date_str,
                        'place': place,
                        'race_no': race_no,
                        'Winning_Numbers': winning_numbers,
                        'Points': points
                    })
                    existing_ids.add(game_id)
                    print(f"✅ 取得成功: {game_id} ({winning_numbers} / {points}円)")
                
                time.sleep(1)
            except Exception as e:
                print(f"❌ エラー ({r_id}): {e}")
                continue

# ==========================================
# 3. 追記・並び替え・保存
# ==========================================
if all_new_results:
    df_new = pd.DataFrame(all_new_results)
    df_merged = pd.concat([df_existing, df_new], ignore_index=True)
    df_merged = df_merged.drop_duplicates(subset=['game_id'])
    
    # 日付順 ➔ 競馬場順 ➔ レース番号順 に綺麗に並び替え
    df_merged['race_no'] = df_merged['race_no'].astype(int)
    df_merged['place_cat'] = pd.Categorical(df_merged['place'], categories=place_order, ordered=True)
    df_merged = df_merged.sort_values(by=['date', 'place_cat', 'race_no']).drop(columns=['place_cat']).reset_index(drop=True)
    
    df_merged.to_csv(master_file, index=False)
    print(f"\n🎉 完了！新たに {len(df_new)} レースを追加しました（合計: {len(df_merged)} レース）")
else:
    print("\nℹ️ 追加すべき新しいレース結果はありませんでした。")
