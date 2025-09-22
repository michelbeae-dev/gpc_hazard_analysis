import os
import math
import traceback
import io
import base64
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
import pandas as pd
import requests
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.font_manager as fm

# --- 1. 한글 폰트 설정 (가장 중요) ---
# 프로젝트에 포함된 ttf 파일 경로를 찾고, 폰트 속성 객체를 생성합니다.
# 이 fontprop 객체를 모든 텍스트에 직접 지정하여 어떤 환경에서든 폰트가 적용되게 합니다.
fontprop = None
try:
    font_path = os.path.join(os.path.dirname(__file__), "NanumGothic-Regular.ttf")
    if os.path.exists(font_path):
        fontprop = fm.FontProperties(fname=font_path)
        print(f"폰트 로드 성공: {font_path}")
    else:
        print(f"Warning: 지정된 경로에 폰트 파일이 없습니다 - {font_path}")
except Exception as e:
    print(f"Warning: Korean font load 실패 - {e}")

# 마이너스 기호가 깨지지 않도록 설정합니다.
plt.rcParams['axes.unicode_minus'] = False

# FastAPI 앱을 초기화합니다.
app = FastAPI()


# --- 2. 분석/시각화 및 유틸리티 함수들 ---
# 이미지를 base64로 인코딩하는 함수는 그대로 사용합니다.
def create_plot_image(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    image_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    buf.close()
    return f"data:image/png;base64,{image_base64}"

# 분류 및 연령대 그룹 함수들도 그대로 사용합니다.
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
        if age <= 6: return '영유아 (0-6세)'
        elif 7 <= age <= 12: return '어린이 (7-12세)'
        elif 13 <= age <= 18: return '청소년 (13-18세)'
        elif 19 <= age <= 39: return '청년 (19-39세)'
        elif 40 <= age <= 64: return '중장년 (40-64세)'
        else: return '노년 (65세 이상)'
    except (ValueError, TypeError):
        return '정보없음'


# --- 3. 백그라운드에서 실행될 메인 분석 함수 ---
# 시간이 오래 걸리는 모든 작업을 이 함수 안으로 옮겼습니다.
def run_analysis_and_save_report(base_url: str, service_key: str):
    report_content = ""
    try:
        # 1. API 호출하여 totalCount 확인
        params_first_page = {'serviceKey': service_key, 'page': 1, 'perPage': 1, 'returnType': 'json'}
        response = requests.get(base_url, params=params_first_page, timeout=30)
        response.raise_for_status()
        total_count = response.json().get('totalCount')
        if total_count is None:
            raise ValueError("API 응답에서 totalCount를 찾을 수 없습니다.")

        # 2. 모든 데이터 다운로드
        all_dfs = []
        per_page = 1000
        total_pages = math.ceil(total_count / per_page)
        for page in range(1, total_pages + 1):
            params_page = {'serviceKey': service_key, 'page': page, 'perPage': per_page, 'returnType': 'json'}
            try:
                response = requests.get(base_url, params=params_page, timeout=30)
                response.raise_for_status()
                df_part = pd.DataFrame(response.json().get('data', []))
                if not df_part.empty: all_dfs.append(df_part)
            except Exception as e:
                print(f"{page}페이지 다운로드 실패: {e}")
        if not all_dfs:
            raise ValueError("전체 페이지에서 데이터를 가져오지 못했습니다.")

        df = pd.concat(all_dfs, ignore_index=True)

        # 3. 데이터 전처리
        required_columns = ['품목소분류', '위험및위해원인 소분류', '위해자연령']
        if not all(col in df.columns for col in required_columns):
            raise ValueError(f"필요한 컬럼이 데이터에 없습니다. 필요한 컬럼: {required_columns}")
        
        df.dropna(subset=['품목소분류', '위험및위해원인 소분류'], inplace=True)
        df['위해자연령'] = pd.to_numeric(df['위해자연령'], errors='coerce')
        df['GPC_Level2'] = df['품목소분류'].apply(classify_gpc_level2)
        df['연령대'] = df['위해자연령'].apply(age_group)

        # 4. 데이터 시각화 (모든 텍스트 요소에 fontproperties=fontprop 직접 지정)
        # --- 그래프 1: GPC Level 2 빈도 ---
        plt.figure(figsize=(12, 8))
        gpc_counts = df['GPC_Level2'].value_counts()
        gpc_plot = sns.barplot(x=gpc_counts.values, y=gpc_counts.index, palette='viridis', orient='h')
        if fontprop:
            gpc_plot.set_title('GPC Level 2 분류별 위해정보 발생 빈도', fontsize=16, fontproperties=fontprop)
            gpc_plot.set_xlabel('발생 빈도', fontproperties=fontprop)
            gpc_plot.set_ylabel('GPC 분류', fontproperties=fontprop)
            plt.xticks(fontproperties=fontprop)
            plt.yticks(fontproperties=fontprop)
            for p in gpc_plot.patches:
                gpc_plot.annotate(f'{int(p.get_width())}', (p.get_width(), p.get_y() + p.get_height() / 2.),
                                  ha='left', va='center', xytext=(5, 0), textcoords='offset points', fontproperties=fontprop)
        gpc_freq_img = create_plot_image(plt.gcf())
        plt.close()

        # --- 그래프 2: 히트맵 ---
        top_gpc_categories = gpc_counts.nlargest(5).index
        df_top_gpc = df[df['GPC_Level2'].isin(top_gpc_categories)]
        top_causes = df['위험및위해원인 소분류'].value_counts().nlargest(7).index
        df_top_causes = df_top_gpc[df_top_gpc['위험및위해원인 소분류'].isin(top_causes)]
        ct_hazard = pd.crosstab(df_top_causes['GPC_Level2'], df_top_causes['위험및위해원인 소분류'])
        plt.figure(figsize=(14, 8))
        heatmap = sns.heatmap(ct_hazard, annot=True, fmt='d', cmap='YlGnBu')
        if fontprop:
            heatmap.set_title('주요 GPC 분류와 위해 원인 간의 상관관계', fontsize=16, fontproperties=fontprop)
            heatmap.set_xlabel('위험 및 위해 원인', fontsize=12, fontproperties=fontprop)
            heatmap.set_ylabel('GPC 분류', fontsize=12, fontproperties=fontprop)
            plt.xticks(rotation=30, ha='right', fontproperties=fontprop)
            plt.yticks(rotation=0, fontproperties=fontprop)
        gpc_cause_corr_img = create_plot_image(plt.gcf())
        plt.close()

        # --- 그래프 3: 연령대 분포 ---
        plt.figure(figsize=(14, 8))
        age_order = ['영유아 (0-6세)', '어린이 (7-12세)', '청소년 (13-18세)', '청년 (19-39세)', '중장년 (40-64세)', '노년 (65세 이상)', '정보없음']
        age_dist_plot = sns.countplot(data=df_top_gpc, x='GPC_Level2', hue='연령대', order=top_gpc_categories, hue_order=age_order, palette='Set2')
        if fontprop:
            age_dist_plot.set_title('주요 GPC 분류별 위해자 연령대 분포', fontsize=16, fontproperties=fontprop)
            age_dist_plot.set_xlabel('GPC 분류', fontproperties=fontprop)
            age_dist_plot.set_ylabel('인원 수', fontproperties=fontprop)
            plt.xticks(rotation=30, ha='right', fontproperties=fontprop)
            plt.yticks(fontproperties=fontprop)
            age_dist_plot.legend(prop=fontprop) # 범례 폰트 지정
        gpc_age_dist_img = create_plot_image(plt.gcf())
        plt.close()

        # 5. HTML 리포트 생성
        report_content = f"""
        <html><head><meta charset="UTF-8"><title>GPC 분석 리포트</title></head><body>
            <h1>GPC 기반 위해정보 심층 분석</h1>
            <h2>1. GPC Level 2 분류별 발생 빈도</h2>
            <img src="{gpc_freq_img}" style="width:100%; height:auto;">
            <h2>2. 주요 GPC 분류와 위해 원인 간 상관관계</h2>
            <img src="{gpc_cause_corr_img}" style="width:100%; height:auto;">
            <h2>3. 주요 GPC 분류별 위해자 연령대 분포</h2>
            <img src="{gpc_age_dist_img}" style="width:100%; height:auto;">
        </body></html>
        """

    except Exception:
        report_content = f"<h3>분석 중 에러 발생:</h3><pre>{traceback.format_exc()}</pre>"
        print("리포트 생성 중 에러 발생")
    
    finally:
        # 성공하든 실패하든 결과를 report.html 파일로 저장
        with open("report.html", "w", encoding="utf-8") as f:
            f.write(report_content)
        print("리포트 파일 생성이 완료되었습니다: report.html")


# --- 4. API 엔드포인트 ---
# n8n이 호출할 엔드포인트: 백그라운드 작업을 시작시키고 즉시 응답
@app.post("/analyze")
async def start_analysis(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        base_url = data.get('URL')
        service_key = os.environ.get('SERVICE_KEY')

        if not all([base_url, service_key]):
            return HTMLResponse(content="<h3>Error: URL 또는 서버의 SERVICE_KEY 정보가 누락되었습니다.</h3>", status_code=400)

        # 백그라운드에서 run_analysis_and_save_report 함수를 실행하도록 예약
        background_tasks.add_task(run_analysis_and_save_report, base_url, service_key)

        # 타임아웃 걱정 없이 바로 응답 반환
        return HTMLResponse(content="<h3>데이터 분석 요청을 접수했습니다. 잠시 후 /report 경로에서 결과를 확인하세요.</h3>")

    except Exception:
        return HTMLResponse(content=f"<h3>요청 처리 중 에러 발생:</h3><pre>{traceback.format_exc()}</pre>", status_code=500)

# 생성된 리포트 파일을 확인하는 엔드포인트
@app.get("/report", response_class=HTMLResponse)
async def get_report():
    report_path = "report.html"
    if os.path.exists(report_path):
        return FileResponse(report_path)
    return HTMLResponse(content="<h3>리포트가 아직 생성되지 않았습니다. 잠시 후 다시 시도해주세요.</h3>", status_code=404)
