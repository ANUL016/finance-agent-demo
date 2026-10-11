import streamlit as st
from pypdf import PdfReader
from dotenv import load_dotenv
import os
import requests

# 加载.env里面的API密钥
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# 初始化API调用计数器
if "api_call_count" not in st.session_state:
    st.session_state.api_call_count = 0
MAX_API_CALL = 3


def call_deepseek_analysis(finance_text):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    # 截断财报文本，只取前3500字符，控制token
    short_text = finance_text[:3500]
    # 前面带f！！填充变量
    prompt = f"""你是财报风险识别智能体。
请基于下面的上市公司财报文本，输出结构化财务风险分析报告：
1. 营收与利润情况概览
2. 重点财务风险识别
3. 风险原因简述
4. 简要建议

财报文本：
{short_text}
"""
    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1200
    }
    try:
        response = requests.post(url, headers=headers, json=body, timeout=60)
        result_json = response.json()
        print("API返回原始数据：", result_json) # 在Anaconda终端打印调试信息

        if "error" in result_json:
            return f"API调用失败！错误信息：{result_json['error']}"

        content = result_json["choices"][0]["message"]["content"]
        if not content.strip():
            return "⚠️大模型返回了空内容！可能财报文本缺少财务数据，请更换包含利润表、资产负债表的年报PDF。"
        return content

    except requests.exceptions.Timeout:
        return "⚠️请求超时！网络较慢或文本太长，请缩短财报文本重试"
    except Exception as e:
        return f"⚠️调用异常：{str(e)}"


# ========== 网页UI界面 ==========
st.set_page_config(page_title="财报风险识别智能体", layout="wide")
st.title("财报风险识别智能体 | 大赛Demo")

uploaded_file = st.file_uploader("上传上市公司财报PDF文件", type="pdf")
pdf_text_content = ""

if uploaded_file is not None:
    reader = PdfReader(uploaded_file)
    full_text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            full_text += page_text
    preview_text = full_text[:2000]
    pdf_text_content = full_text

    st.subheader("文件预览（提取文本前2000字符）")
    st.text_area("PDF提取内容", preview_text, height=300)

    # 分析按钮
    if st.button("启动AI智能体分析财报"):
        if not DEEPSEEK_API_KEY:
            st.error("⚠️ 未读取到API密钥，请检查.env文件！")
        elif st.session_state.api_call_count >= MAX_API_CALL:
            st.warning("本次演示API调用次数已用完，无法继续分析")
        else:
            with st.spinner("DeepSeek正在读取财报，生成风险报告，请稍候..."):
                analysis_result = call_deepseek_analysis(pdf_text_content)
                st.session_state.api_call_count += 1
                st.markdown("# 智能体分析报告")
                st.markdown(analysis_result)