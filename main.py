import os
import math
import traceback
import io
import base64
import urllib.parse
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import pandas as pd
import requests
import matplotlib.pyplot as plt
import seaborn as sns

app = FastAPI()

# 1. 한글 폰트 설정 (이 부분은 그대로 두세요)
try:
    plt.rc('font', family='Malgun Gothic')
except:
    try:
        plt.rc('font', family='AppleGothic')
    except:
        print("Warning: Korean font not found.")
plt.rcParams['axes.unicode_minus'] = False

# 2. 분석/시각화 함수들 (제공해주신 코드를 함수로 만들었습니다)
# ... (create_plot_image, classify_gpc_level2, age_group 함수는 변경 없습니다) ...
def create_plot_image(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    image_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    buf.close()
    return f"data:image/png;base64,{image_base64}"

def classify_gpc_level2(item):
    item_str = str(item).lower()
    if any(x in item_str for x in ['침대', '소파', '의자', '책상', '장롱', '가구', '선반', '계단', '문', '창문']): return '가구 및 비품'
    if any(x in item_str for x in ['인덕션', '전기장판', '보일러', '세탁기', '냉장고', '에어컨', '전자레인지', '밥솥', '청소기']): return '가전제품'
    if any(x in item_str for x in ['가공식품', '음료', '주류', '건강기능식품', '담배']): return '식품/음료/담배'
    if any(x in item_str for x in ['자동차', '자전거', '오토바이', '킥보드', '타이어']): return '차량 및 부품'
    if any(x in item_str for x in ['화장품', '세제', '샴푸', '치약', '살충제']): return '미용/위생/화학제품'
    if any(x in item_str for x in ['장난감', '완구', '게임기']): return '장난감 및 게임'
    if any(x in item_str for x in ['의류', '신발', '가방']): return '의류 및 신발'
    if any(x in item_str for x in ['휴대폰', '노트북', '배터리', '컴퓨터']): return '통신/사무기기'
    if any(x in item_str for x in ['의약품', '의료기기']): return '의약품 및 의료기기'
    return '기타'

def age_group(age):
    if pd.isna(age): return '정보없음'
    try:
        age = int(age)
        if age <= 6: return '영유아 (0-6세)'
        elif 7 <= age <= 12: return '어린이 (7-12세)'
        elif 13 <= age <= 18: return '청소년 (13-18세)'
        elif 19 <= age <= 39: return '청년 (19-39세)'
        elif 40 <= age <= 64: return '중장년 (40-64세)'
        else: return '노년 (65세 이상)'
    except (ValueError, TypeError):
        return '정보없음'

# 3. n8n이 호출할 메인 API 함수 (최종 수정)
@app.post("/analyze", response_class=HTMLResponse)
async def analyze_data(request: Request):
    try:
        data = await request.json()
        path = data.get('path')
        total_count_str = data.get('totalCount')
        year = data.get('year', 'N/A')
        
        # Render 환경 변수에서 서비스 키를 안전하게 불러옵니다.
        service_key = os.environ.get('SERVICE_KEY')

        if not all([path, total_count_str, service_key]):
            return HTMLResponse(content="<h3>Error: path, totalCount, 또는 서버의 SERVICE_KEY 정보가 누락되었습니다.</h3>", status_code=400)
        
        total_count = int(total_count_str)
        per_page = 1000
        total_pages = math.ceil(total_count / per_page)
        
        urls_to_fetch = []
        for page in range(1, total_pages + 1):
            url = f"https://api.odcloud.kr{path}?page={page}&perPage={per_page}&serviceKey={service_key}"
            urls_to_fetch.append(url)

        all_dfs = []
        for url in urls_to_fetch:
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                json_data = response.json()
                df_part = pd.DataFrame(json_data.get('data', []))
                if not df_part.empty:
                    all_dfs.append(df_part)
            except Exception as e:
                print(f"URL 다운로드 실패: {url}, 에러: {e}")
        
        if not all_dfs:
            return HTMLResponse(content="<h3>Error: URL에서 데이터를 가져올 수 없습니다.</h3>", status_code=400)

        df = pd.concat(all_dfs, ignore_index=True)

        # (이하 분석 및 리포트 생성 코드는 변경 없습니다)
        df.dropna(subset=['위해품목', '위험및위해원인'], inplace=True)
        age_column = '위해자연령' if '위해자연령' in df.columns else '위해자나이'
        df[age_column] = pd.to_numeric(df[age_column], errors='coerce')
        df['GPC_Level2'] = df['위해품목'].apply(classify_gpc_level2)
        df['연령대'] = df[age_column].apply(age_group)

        # 분석 1: GPC 빈도
        plt.figure(figsize=(12, 8))
        gpc_counts = df['GPC_Level2'].value_counts()
        gpc_plot = sns.barplot(x=gpc_counts.values, y=gpc_counts.index, palette='viridis', orient='h')
        gpc_plot.set_title(f'{year}년 GPC Level 2 분류별 위해정보 발생 빈도', fontsize=16)
        for p in gpc_plot.patches:
            gpc_plot.annotate(f'{int(p.get_width())}', (p.get_width(), p.get_y() + p.get_height() / 2.), ha='left', va='center', xytext=(5, 0), textcoords='offset points')
        gpc_freq_img = create_plot_image(plt.gcf())
        plt.close()
        
        # (이하 분석 2, 3 및 HTML 생성 코드)
        top_gpc_categories = gpc_counts.nlargest(5).index
        df_top_gpc = df[df['GPC_Level2'].isin(top_gpc_categories)]
        top_causes = df['위험및위해원인'].value_counts().nlargest(7).index
        df_top_causes = df_top_gpc[df_top_gpc['위험및위해원인'].isin(top_causes)]
        ct_hazard = pd.crosstab(df_top_causes['GPC_Level2'], df_top_causes['위험및위해원인'])
        plt.figure(figsize=(14, 8))
        heatmap = sns.heatmap(ct_hazard, annot=True, fmt='d', cmap='YlGnBu')
        heatmap.set_title('주요 GPC 분류와 위해 원인 간의 상관관계', fontsize=16)
        plt.xticks(rotation=30, ha='right')
        gpc_cause_corr_img = create_plot_image(plt.gcf())
        plt.close()
        
        plt.figure(figsize=(14, 8))
        age_order = ['영유아 (0-6세)', '어린이 (7-12세)', '청소년 (13-18세)', '청년 (19-39세)', '중장년 (40-64세)', '노년 (65세 이상)', '정보없음']
        age_dist_plot = sns.countplot(data=df_top_gpc, x='GPC_Level2', hue='연령대', order=top_gpc_categories, hue_order=age_order, palette='Set2')
        age_dist_plot.set_title('주요 GPC 분류별 위해자 연령대 분포', fontsize=16)
        plt.xticks(rotation=30, ha='right')
        gpc_age_dist_img = create_plot_image(plt.gcf())
        plt.close()
        
        html_report = f"""
        <html><head><meta charset="UTF-8"></head><body>
            <h1>GPC 기반 위해정보 심층 분석 ({year}년)</h1>
            <h2>1. GPC Level 2 분류별 발생 빈도</h2>
            <img src="{gpc_freq_img}" style="width:100%; height:auto;">
            <h2>2. 주요 GPC 분류와 위해 원인 간 상관관계</h2>
            <img src="{gpc_cause_corr_img}" style="width:100%; height:auto;">
            <h2>3. 주요 GPC 분류별 위해자 연령대 분포</h2>
            <img src="{gpc_age_dist_img}" style="width:100%; height:auto;">
        </body></html>
        """
        return HTMLResponse(content=html_report)

    except Exception:
        return HTMLResponse(content=f"<h3>분석 중 에러 발생:</h3><pre>{traceback.format_exc()}</pre>", status_code=500)
