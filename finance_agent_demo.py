import streamlit as st
import os
from dotenv import load_dotenv
import requests
import pypdf
import json

# 加载环境变量，读取DeepSeek密钥
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# ======================【财务计算引擎：指标100%由代码引擎计算，大模型不做算术】======================
def clean_number(val):
    """清洗数字，去掉千分位逗号，无法转换返回None"""
    if val is None:
        return None
    s = str(val).replace(",", "")
    try:
        return float(s)
    except:
        return None

def calc_financial_index(data):
    # 清洗所有财务数据
    current_asset = clean_number(data.get("流动资产"))
    current_liab = clean_number(data.get("流动负债"))
    total_asset = clean_number(data.get("总资产"))
    total_liab = clean_number(data.get("总负债"))
    net_profit = clean_number(data.get("净利润"))
    cash_operate = clean_number(data.get("经营现金流净额"))

    res = {}
    # 流动比率
    if current_asset and current_liab and current_liab != 0:
        res["流动比率"] = round(current_asset / current_liab,3)
    else:
        res["流动比率"] = "数据不足"
    # 资产负债率
    if total_asset and total_asset !=0:
        res["资产负债率"] = round(total_liab / total_asset,3)
    else:
        res["资产负债率"] = "数据不足"
    # 净利润
    res["净利润"] = net_profit if net_profit else "未提取"
    # 经营现金流
    res["经营现金流净额"] = cash_operate if cash_operate else "未提取"
    return res
# ======================【PDF解析：提取文本+记录每段对应的页码（溯源核心）】======================
def read_pdf_with_page(file):
    pdf_reader = pypdf.PdfReader(file)
    page_text_list = []
    for page_idx, page in enumerate(pdf_reader.pages):
        page_num = page_idx + 1 # 财报页码从1开始
        text = page.extract_text()
        if text.strip():
            page_text_list.append({
                "page": page_num,
                "content": text.strip()
            })
    full_text = "\n".join([f"【页码{p['page']}】{p['content']}" for p in page_text_list])
    return full_text, page_text_list

# ====================== 调用DeepSeek API通用函数 ======================
def call_deepseek(messages, temperature=0.1):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "timeout": 120
    }
    resp = requests.post(DEEPSEEK_URL, headers=headers, json=payload)
    return resp.json()

# ====================== Agent1：主分析Agent（修复增强版） ======================
def analysis_agent(full_text, page_list):
    prompt = f"""
你是财报分析师，基于下面带页码标记的财报原文做分析。
原文：
{full_text}

任务：
1. 提取财报内基础财务数据：流动资产、流动负债、总资产、总负债、净利润、经营现金流净额；
2. 输出提取到的原始数字，不要自己估算；
3. 识别财报风险，**每一条风险结论必须标注引用的页码+原文片段作为证据**；
4. 只输出JSON，**禁止任何额外解释、前言、说明文字**。
输出严格JSON格式：
{{
"raw_fin_data": {{提取到的财务原始数字}},
"risk_list": [
    {{
        "conclusion":风险结论文字,
        "quote_page":引用页码,
        "quote_text":对应的财报原文片段
    }}
]
}}
找不到的数据填null。
"""
    msg = [{"role":"user","content":prompt}]
    api_result = call_deepseek(msg)
    reply = api_result["choices"][0]["message"]["content"]
    # 清洗字符串，只截取{}之间的JSON内容，解决模型额外文字污染
    import re
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if match:
        json_str = match.group(0)
        try:
            return json.loads(json_str)
        except:
            pass
    return {"raw_fin_data":{}, "risk_list":[]}
# ====================== Agent2：质疑/审计挑错Agent【新增！双Agent核心】 ======================
def audit_agent(full_text, page_data, risk_list):
    prompt = f"""
你是独立审计复核专家，对照财报原文，逐条校验下面每一条风险结论：
{risk_list}
财报原文：
{full_text}

任务：
1. 逐条核对每一条风险：看结论、引用页码、原文证据是否匹配财报；
2. 判断这条结论是否属于AI幻觉；
3. 输出JSON，**禁止任何多余前言、解释**。
输出格式：
{{
"confidence": 0~1之间的置信度,
"doubt_list":[
    {{
        "target_conclusion":"风险结论原文",
        "doubt_reason":"核验理由",
        "is_hallucination": true/false
    }}
],
"summary":"审计总结一句话"
}}
"""
    msg = [{"role":"user","content":prompt}]
    api_result = call_deepseek(msg)
    reply = api_result["choices"][0]["message"]["content"]
    # JSON清洗，只提取大括号内JSON
    import re
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if match:
        json_str = match.group(0)
        try:
            return json.loads(json_str)
        except Exception as e:
            pass
    # 解析失败兜底返回
    return {"confidence":0.5,"doubt_list":[],"summary":"审计解析失败"}# ===================== Streamlit前端页面 ======================
st.set_page_config(page_title="财报审计智能体", layout="wide")
st.title("财报风险审计智能体｜双Agent可审计闭环系统")

uploaded_file = st.file_uploader("上传上市公司财报PDF",type="pdf")
if uploaded_file is not None:
    with st.spinner("正在读取PDF，提取文本+记录页码..."):
        full_txt, page_data = read_pdf_with_page(uploaded_file)
    st.success("PDF读取完成，已保存每页溯源信息")

    if st.button("启动双Agent财报分析与审计"):
        # 1. 执行分析Agent
        with st.spinner("【分析Agent】正在提取数据、识别风险..."):
            analysis_out = analysis_agent(full_txt, page_data)
        st.subheader("一、主Agent 分析结果")
        st.json(analysis_out)

        # 2. 财务引擎计算指标（大模型不参与计算）
        fin_result = calc_financial_index(analysis_out["raw_fin_data"])
        st.subheader("二、财务引擎计算结果（100%代码引擎计算）")
        st.write(fin_result)

        #3. 质疑审计Agent挑错校验
        with st.spinner("【审计质疑Agent】正在校验结论、查找幻觉与引用错误..."):
            audit_result = audit_agent(full_txt, page_data, analysis_out)
        st.subheader("三、审计Agent校验结果（证据链+置信度）")
        st.json(audit_result)

         # ---------------------- 4. 整合审计轨迹报告 + 美化展示【替换这一整段】 ----------------------
        st.subheader("📊 一、引擎计算财务指标")
        if fin_result:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("流动比率", fin_result.get("流动比率", "数据不足"))
                st.metric("净利润", fin_result.get("净利润", "未提取"))
            with col2:
                st.metric("资产负债率", fin_result.get("资产负债率", "数据不足"))
                st.metric("经营现金流净额", fin_result.get("经营现金流净额", "未提取"))
        else:
            st.warning("财务指标提取失败，数据不足")

        st.subheader("⚠️ 二、识别到的财报风险清单（带原文溯源）")
        risk_list = analysis_out.get("risk_list", [])
        if len(risk_list) > 0:
            for idx, risk in enumerate(risk_list):
                with st.expander(f"风险 {idx+1}：{risk.get('conclusion','无结论')}", expanded=False):
                    st.markdown(f"""
                    - 📄 引用页码：**{risk.get('quote_page','无')}**
                    - 📝 原文证据：
                    > {risk.get('quote_text','无原文')}
                    """)
        else:
            st.info("本次未识别出财报风险")


        st.subheader("✅ 三、审计校验汇总结果")
        audit_conf = audit_result.get("confidence", 0)
        st.metric("审计置信度", audit_conf)
        st.markdown(f"**审计总结：** {audit_result.get('summary','无总结')}")

        st.markdown("#### 🔍 逐条核验详情（可展开查看）")
        doubt_list = audit_result.get("doubt_list", [])
        if len(doubt_list) > 0:
            for idx, item in enumerate(doubt_list):
                with st.expander(f"核验记录 {idx+1}", expanded=False):
                    st.write(f"目标结论：{item.get('target_conclusion','')}")
                    st.write(f"核验说明：{item.get('doubt_reason','')}")
                    st.write(f"是否幻觉：{item.get('is_hallucination','')}")
        else:
            st.success("无异常核验疑点")


        # 折叠原始JSON（答辩时不用展示，需要再点开）
        with st.expander("📜 原始底层JSON数据（调试用）", expanded=False):
            st.json(analysis_out)
            st.json(audit_result)


        # 组装导出用完整报告文本（和之前内容完全一致，导出文件不变）
        final_report = f"""
# 财报审计报告
## 1.提取原始财务数据
{json.dumps(analysis_out['raw_fin_data'],ensure_ascii=False,indent=2)}
## 2.引擎计算财务指标
{json.dumps(fin_result,ensure_ascii=False,indent=2)}
## 3.风险结论与原文证据
"""
        for risk in analysis_out["risk_list"]:
            final_report += f"\n>结论：{risk['conclusion']}\n>引用页码：{risk['quote_page']}\n>原文证据：{risk['quote_text']}\n"
        final_report += f"""
## 4.审计校验记录
置信度：{audit_result['confidence']}
审计疑点：{json.dumps(audit_result['doubt_list'],ensure_ascii=False)}
审计总结：{audit_result['summary']}
"""

        st.divider()
        st.download_button(
            label="📥 一键导出带审计轨迹报告",
            data=final_report,
            file_name="财报审计报告.md",
            mime="text/markdown"
        )