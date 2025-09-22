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
import matplotlib.font_manager as fm

# 1. 한글 폰트 설정 (프로젝트 포함 TTF 사용)
try:
    font_path = os.path.join(os.path.dirname(__file__), "NanumGothic-Regular.ttf")
    fontprop = fm.FontProperties(fname=font_path)
    plt.rc('font', family=fontprop.get_name())
    print(f"폰트 적용됨: {fontprop.get_name()}")
except Exception as e:
    print(f"Warning: Korean font load 실패 - {e}")
    plt.rc('font', family='DejaVu Sans')  # fallback
plt.rcParams['axes.unicode_minus'] = False


app = FastAPI()



plt.rcParams['axes.unicode_minus'] = False


# 2. 분석/시각화 함수들
def create_plot_image(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    image_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    buf.close()
    return f"data:image/png;base64,{image_base64}"


def classify_gpc_level2(item):
    item_str = str(item).lower()
    if any(x in item_str for x in ['침대', '소파', '의자', '책상', '장롱', '가구', '선반', '계단', '문', '창문']):
        return '가구 및 비품'
    if any(x in item_str for x in ['인덕션', '전기장판', '보일러', '세탁기', '냉장고', '에어컨', '전자레인지', '밥솥', '청소기']):
        return '가전제품'
    if any(x in item_str for x in ['가공식품', '음료', '주류', '건강기능식품', '담배']):
        return '식품/음료/담배'
    if any(x in item_str for x in ['자동차', '자전거', '오토바이', '킥보드', '타이어']):
        return '차량 및 부품'
    if any(x in item_str for x in ['화장품', '세제', '샴푸', '치약', '살충제']):
        return '미용/위생/화학제품'
    if any(x in item_str for x in ['장난감', '완구', '게임기']):
        return '장난감 및 게임'
    if any(x in item_str for x in ['의류', '신발', '가방']):
        return '의류 및 신발'
    if any(x in item_str for x in ['휴대폰', '노트북', '배터리', '컴퓨터']):
        return '통신/사무기기'
    if any(x in item_str for x in ['의약품', '의료기기']):
        return '의약품 및 의료기기'
    return '기타'


def age_group(age):
    if pd.isna(age):
        return '정보없음'
    try:
        age = int(age)
        if age <= 6:
            return '영유아 (0-6세)'
        elif 7 <= age <= 12:
            return '어린이 (7-12세)'
        elif 13 <= age <= 18:
            return '청소년 (13-18세)'
        elif 19 <= age <= 39:
            return '청년 (19-39세)'
        elif 40 <= age <= 64:
            return '중장년 (40-64세)'
        else:
            return '노년 (65세 이상)'
    except (ValueError, TypeError):
        return '정보없음'


# 3. n8n이 호출할 메인 API 함수
@app.post("/analyze", response_class=HTMLResponse)
async def analyze_data(request: Request):
    try:
        data = await request.json()
        base_url = data.get('URL')
        service_key = os.environ.get('SERVICE_KEY')

        if not all([base_url, service_key]):
            return HTMLResponse(content="<h3>Error: URL 또는 서버의 SERVICE_KEY 정보가 누락되었습니다.</h3>", status_code=400)

        # 1. 첫 페이지를 호출하여 totalCount를 알아냅니다.
        params_first_page = {'serviceKey': service_key, 'page': 1, 'perPage': 1, 'returnType': 'json'}
        response = requests.get(base_url, params=params_first_page, timeout=30)
        response.raise_for_status()
        first_page_data = response.json()
        total_count = first_page_data.get('totalCount')

        if total_count is None:
            return HTMLResponse(content="<h3>Error: API 응답에서 totalCount를 찾을 수 없습니다.</h3>", status_code=400)

        # 2. 전체 페이지를 순회하며 모든 데이터를 다운로드합니다.
        all_dfs = []
        per_page = 1000
        total_pages = math.ceil(total_count / per_page)
        for page in range(1, total_pages + 1):
            params_page = {'serviceKey': service_key, 'page': page, 'perPage': per_page, 'returnType': 'json'}
            try:
                response = requests.get(base_url, params=params_page, timeout=30)
                response.raise_for_status()
                json_data = response.json()
                df_part = pd.DataFrame(json_data.get('data', []))
                if not df_part.empty:
                    all_dfs.append(df_part)
            except Exception as e:
                print(f"{page}페이지 다운로드 실패: {e}")

        if not all_dfs:
            return HTMLResponse(content="<h3>Error: 전체 페이지에서 데이터를 가져오지 못했습니다.</h3>", status_code=400)

        df = pd.concat(all_dfs, ignore_index=True)

        # 3. 실제 데이터 컬럼 이름에 맞춰 분석을 수행합니다.
        required_columns = ['품목소분류', '위험및위해원인 소분류', '위해자연령']
        if not all(col in df.columns for col in required_columns):
            return HTMLResponse(content=f"<h3>Error: 필요한 컬럼이 데이터에 없습니다. 필요한 컬럼: {required_columns}</h3>", status_code=400)

        df.dropna(subset=['품목소분류', '위험및위해원인 소분류'], inplace=True)
        df['위해자연령'] = pd.to_numeric(df['위해자연령'], errors='coerce')
        df['GPC_Level2'] = df['품목소분류'].apply(classify_gpc_level2)
        df['연령대'] = df['위해자연령'].apply(age_group)

        # 4. 데이터 시각화
        plt.figure(figsize=(12, 8))
        gpc_counts = df['GPC_Level2'].value_counts()
        gpc_plot = sns.barplot(x=gpc_counts.values, y=gpc_counts.index, palette='viridis', orient='h')
        gpc_plot.set_title(f'GPC Level 2 분류별 위해정보 발생 빈도', fontsize=16)
        for p in gpc_plot.patches:
            gpc_plot.annotate(f'{int(p.get_width())}', (p.get_width(), p.get_y() + p.get_height() / 2.),
                              ha='left', va='center', xytext=(5, 0), textcoords='offset points')
        gpc_freq_img = create_plot_image(plt.gcf())
        plt.close()

        top_gpc_categories = gpc_counts.nlargest(5).index
        df_top_gpc = df[df['GPC_Level2'].isin(top_gpc_categories)]
        top_causes = df['위험및위해원인 소분류'].value_counts().nlargest(7).index
        df_top_causes = df_top_gpc[df_top_gpc['위험및위해원인 소분류'].isin(top_causes)]
        ct_hazard = pd.crosstab(df_top_causes['GPC_Level2'], df_top_causes['위험및위해원인 소분류'])
        plt.figure(figsize=(14, 8))
        heatmap = sns.heatmap(ct_hazard, annot=True, fmt='d', cmap='YlGnBu')
        heatmap.set_title('주요 GPC 분류와 위해 원인 간의 상관관계', fontsize=16)
        heatmap.set_xlabel('위험 및 위해 원인', fontsize=12)
        heatmap.set_ylabel('GPC 분류', fontsize=12)
        plt.xticks(rotation=30, ha='right')
        gpc_cause_corr_img = create_plot_image(plt.gcf())
        plt.close()

        plt.figure(figsize=(14, 8))
        age_order = ['영유아 (0-6세)', '어린이 (7-12세)', '청소년 (13-18세)', '청년 (19-39세)',
                     '중장년 (40-64세)', '노년 (65세 이상)', '정보없음']
        age_dist_plot = sns.countplot(data=df_top_gpc, x='GPC_Level2', hue='연령대',
                                      order=top_gpc_categories, hue_order=age_order, palette='Set2')
        age_dist_plot.set_title('주요 GPC 분류별 위해자 연령대 분포', fontsize=16)
        plt.xticks(rotation=30, ha='right')
        gpc_age_dist_img = create_plot_image(plt.gcf())
        plt.close()

        # 5. HTML 리포트 생성
        html_report = f"""
        <html><head><meta charset="UTF-8"></head><body>
            <h1>GPC 기반 위해정보 심층 분석</h1>
            <h2>1. GPC Level 2 분류별 발생 빈도</h2>
            <img src="{gpc_freq_img}" style="width:100%; height:auto;">
            <h2>2. 주요 GPC 분류와 위해 원인 간 상관관계</h2>
            <img src="{gpc_cause_corr_img}" style="width:100%; height:auto;">
            <h2>3. 주요 GPC 분류별 위해자 연령대 분포</h2>
            <img src="{gpc_age_dist_img}" style="width:100%; height:auto;">
        </body></html>
        """
        return HTMLResponse(content=html_report, media_type="text/html; charset=utf-8")

    except Exception:
        return HTMLResponse(content=f"<h3>분석 중 에러 발생:</h3><pre>{traceback.format_exc()}</pre>", status_code=500)
