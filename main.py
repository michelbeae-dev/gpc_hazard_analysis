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
import matplotlib.font_manager as fm
import seaborn as sns

app = FastAPI()

# --- 폰트 설정 (이전과 동일) ---
# ...

# --- 분석/시각화 함수들 (이전과 동일) ---
# ...

# --- 메인 API 함수 (메모리 최적화) ---
@app.post("/analyze", response_class=HTMLResponse)
async def analyze_data(request: Request):
    try:
        data = await request.json()
        base_url = data.get('URL')
        service_key = os.environ.get('SERVICE_KEY')

        if not all([base_url, service_key]):
            return HTMLResponse(content="<h3>Error: URL 또는 서버 SERVICE_KEY 누락</h3>", status_code=400)

        # 1. 첫 페이지 호출하여 totalCount 알아내기
        params_first_page = {'serviceKey': service_key, 'page': 1, 'perPage': 1, 'returnType': 'json'}
        response = requests.get(base_url, params=params_first_page, timeout=30)
        response.raise_for_status()
        total_count = response.json().get('totalCount')

        if total_count is None:
            return HTMLResponse(content="<h3>Error: totalCount를 찾을 수 없음</h3>", status_code=400)

        # --- *** 수정된 부분 시작 *** ---
        # 2. 페이지를 하나씩 처리하여 메모리 사용량 최소화
        
        # 빈 데이터프레임을 먼저 생성
        final_df = pd.DataFrame()
        
        per_page = 1000
        total_pages = math.ceil(total_count / per_page)

        for page in range(1, total_pages + 1):
            params_page = {'serviceKey': service_key, 'page': page, 'perPage': per_page, 'returnType': 'json'}
            try:
                response = requests.get(base_url, params=params_page, timeout=30)
                response.raise_for_status()
                json_data = response.json().get('data', [])
                if json_data:
                    # 다운로드한 데이터를 즉시 데이터프레임으로 만들고,
                    # 기존 데이터프레임에 바로 합칩니다.
                    page_df = pd.DataFrame(json_data)
                    final_df = pd.concat([final_df, page_df], ignore_index=True)
                print(f"{page}/{total_pages} 페이지 처리 완료, 현재 데이터 수: {len(final_df)}")

            except Exception as e:
                print(f"{page}페이지 다운로드 실패: {e}")
        
        if final_df.empty:
            return HTMLResponse(content="<h3>Error: 데이터를 가져오지 못했습니다.</h3>", status_code=400)
        
        # 이제 합쳐진 final_df를 사용합니다.
        df = final_df 
        # --- *** 수정된 부분 끝 *** ---

        # 3. 데이터 분석 및 시각화 (이하 로직은 이전과 동일)
        df.dropna(subset=['품목소분류', '위험및위해원인 소분류'], inplace=True)
        age_column = '위해자연령' if '위해자연령' in df.columns else '위해자나이'
        df[age_column] = pd.to_numeric(df[age_column], errors='coerce')
        df['GPC_Level2'] = df['품목소분류'].apply(classify_gpc_level2)
        df['연령대'] = df[age_column].apply(age_group)

        # (이하 분석 및 HTML 리포트 생성 코드는 변경 없습니다)
        # ...
        
        html_report = f"""
        <html>...</html> 
        """ # 리포트 생성 부분은 생략
        return HTMLResponse(content=html_report)

    except Exception:
        return HTMLResponse(content=f"<h3>분석 중 에러 발생:</h3><pre>{traceback.format_exc()}</pre>", status_code=500)
