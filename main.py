import os
import math
import traceback
import io
import base64
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

# 2. 분석/시각화 함수들 (이전과 동일, 변경 없음)
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

# 3. n8n이 호출할 메인 API 함수 (수정된 부분)
@app.post("/analyze", response_class=HTMLResponse)
async def analyze_data(request: Request):
    try:
        data = await request.json()
        
        # *** 수정된 부분: urls 대신 path와 totalCount를 받습니다 ***
        path = data.get('path')
        total_count_str = data.get('totalCount')
        year = data.get('year', 'N/A')
        
        # Render 환경 변수에서 서비스 키를 안전하게 불러옵니다.
        service_key = os.environ.get('SERVICE_KEY')

        if not all([path, total_count_str, service_key]):
            return HTMLResponse(content="<h3>Error: path, totalCount, 또는 서버의 SERVICE_KEY 정보가 누락되었습니다.</h3>", status_code=400)
        
        # *** 새로 추가된 부분: 받은 정보로 URL 목록을 직접 생성합니다 ***
        total_count = int(total_count_str)
        per_page = 1000
        total_pages = math.ceil(total_count / per_page)
        
        urls_to_fetch = []
        for page in range(1, total_pages + 1):
            url = f"https://api.odcloud.kr{path}?page={page}&perPage={per_page}&serviceKey={service_key}"
            urls_to_fetch.append(url)

        all_dfs = []
        # 생성된 URL 목록을 순회하며 데이터를 다운로드합니다.
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
            return HTMLResponse(content="<h3>Error: URL에서 데이터를 가져오지 못했습니다.</h3>", status_code=400)

        df = pd.concat(all_dfs, ignore_index=True)

        # (이하 분석 및 리포트 생성 코드는 변경 없습니다)
        # ...
        
        html_report = f"""
        <html><head><meta charset="UTF-8"></head><body>
            <h1>GPC 기반 위해정보 심층 분석 ({year}년)</h1>
            <h2>1. GPC Level 2 분류별 발생 빈도</h2>
            <img src="{...}" style="width:100%; height:auto;">
            ...
        </body></html>
        """
        return HTMLResponse(content=html_report)

    except Exception:
        return HTMLResponse(content=f"<h3>분석 중 에러 발생:</h3><pre>{traceback.format_exc()}</pre>", status_code=500)
