"""Streamlit UI for Retail Memory."""
import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# 1. Configuration & API Endpoints
# -----------------------------------------------------------------------------
# Derive the base URL (handles both local dev and Render deployment)
# Derive the base URL (handles both local dev and Render deployment)
base_url_env = os.getenv("RETAIL_MEMORY_API_URL") or "http://127.0.0.1:8000"
BASE_URL = base_url_env.replace("/chat", "")
API_URL = f"{BASE_URL}/chat"
HEALTH_URL = f"{BASE_URL}/health"
# -----------------------------------------------------------------------------
# 2. Page Config & CSS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Retail Memory | Data Lab",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Inter:wght@400;500;600&display=swap');
    
    :root {
        --bg-color: #F8FAFC;
        --text-main: #1E293B;
        --text-muted: #64748B;
        --accent: #4F46E5;
        --accent-light: #EEF2FF;
        --card-bg: #FFFFFF;
        --border: #E2E8F0;
    }

    .stApp { background-color: var(--bg-color); font-family: 'Inter', sans-serif; color: var(--text-main); }
    h1, h2, h3, h4 { font-family: 'Outfit', sans-serif !important; color: var(--text-main); }

    .block-container { max-width: 1200px; padding-top: 2rem; padding-bottom: 2rem; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 24px; border-bottom: 2px solid var(--border); }
    .stTabs [data-baseweb="tab"] { font-family: 'Outfit', sans-serif; font-weight: 600; color: var(--text-muted); padding-bottom: 12px; }
    .stTabs [aria-selected="true"] { color: var(--accent) !important; border-bottom: 2px solid var(--accent) !important; }

    /* Chat Bubbles */
    [data-testid="stChatMessage"] {
        border-radius: 16px; padding: 1.5rem; margin-bottom: 1rem;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); border: 1px solid var(--border);
    }
    [data-testid="stChatMessage"]:nth-child(odd) { background-color: #FFFFFF; }
    [data-testid="stChatMessage"]:nth-child(even) { background-color: #F1F5F9; }

    /* Tool Badge */
    .tool-badge {
        display: inline-flex; background-color: var(--accent-light); color: var(--accent);
        padding: 6px 14px; border-radius: 20px; font-family: 'Courier New', monospace;
        font-size: 0.8rem; font-weight: 700; margin-top: 12px; border: 1px solid #C7D2FE;
    }

    /* Cards */
    .fun-card {
        background-color: var(--card-bg); border-radius: 16px; padding: 1.5rem;
        border: 1px solid var(--border); box-shadow: 0 4px 20px -2px rgba(0,0,0,0.03);
        transition: all 0.3s ease; margin-bottom: 1rem;
    }
    .fun-card:hover { transform: translateY(-4px); box-shadow: 0 12px 25px -5px rgba(79, 70, 229, 0.15); border-color: #A5B4FC; }
    .fun-card h3 { margin-top: 0; font-size: 1.3rem; color: var(--accent); }
    .analogy-text { font-size: 1rem; line-height: 1.6; color: var(--text-main); }

    /* Sidebar Buttons */
    .stButton > button {
        background-color: #FFFFFF; color: var(--text-main); border: 1px solid var(--border);
        border-radius: 10px; padding: 0.6rem 1rem; font-family: 'Inter', sans-serif;
        font-weight: 500; text-align: left; transition: all 0.2s; width: 100%;
    }
    .stButton > button:hover { border-color: var(--accent); color: var(--accent); background-color: var(--accent-light); }
    
    /* Hide Footer */
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 3. Cached Health Check
# -----------------------------------------------------------------------------
@st.cache_data(ttl=30)
def check_backend_health():
    """Checks API status safely, preventing Streamlit crashes if backend is asleep."""
    try:
        r = requests.get(HEALTH_URL, timeout=2)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False

# -----------------------------------------------------------------------------
# 4. State Management
# -----------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

def start_new_chat():
    st.session_state.messages = []
    st.session_state.pending_prompt = None
    st.toast("Chat cleared!", icon="🗑️")

def queue_prompt(prompt_text):
    st.session_state.pending_prompt = prompt_text
    st.toast("Question queued!", icon="💡")

# -----------------------------------------------------------------------------
# 5. Sidebar
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("<h2>🧪 Retail Memory</h2>", unsafe_allow_html=True)
    st.markdown("The ultimate tool to understand retail pricing.")
    st.divider()
    
    if check_backend_health():
        st.success("🟢 Backend API is Online")
    else:
        st.error("🔴 Backend API is Offline or Waking Up\n\n*(Render free tier takes ~45s to cold-start)*")
    
    st.divider()
    st.markdown("### 💡 Suggested Questions")
    st.caption("Click any question to instantly run it.")
    
    if st.button("📊 Sales: Milk (Weeks 1-20)"):
        queue_prompt("What were the total sales for product 995242 between weeks 1 and 20?")
    if st.button("🏷️ Discount: Strawberries (30%)"):
        queue_prompt("Should I discount product 1127831 assuming a 30% margin?")
    if st.button("🥩 Cannibalization Test"):
        queue_prompt("Is product 1127831 cannibalizing product 860299?")
    
    st.divider()
    st.markdown("### 🛡️ Test Guardrails")
    if st.button("🤔 Vague Question"):
        queue_prompt("Is product 995242 doing well?")
    if st.button("🚫 Out of Scope"):
        queue_prompt("What's the weather today?")

    st.divider()
    if st.button("🗑️ Start New Chat", type="primary"):
        start_new_chat()
        st.rerun()

# -----------------------------------------------------------------------------
# 6. Main Layout
# -----------------------------------------------------------------------------
st.markdown("<h1 style='text-align: center; font-size: 3rem; margin-bottom: 0;'>Retail Memory</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; font-size: 1.2rem; color: #64748B; margin-bottom: 2rem;'>The Data Lab: Discovering if your discounts are working—or just eating your margin.</p>", unsafe_allow_html=True)

tab_chat, tab_lab = st.tabs(["💬 AI Assistant", "🔬 The Data Lab"])

# =============================================================================
# TAB 1: AI ASSISTANT (CHAT)
# =============================================================================
with tab_chat:
    # 1. Render Chat History
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar="👤" if message["role"] == "user" else "🤖"):
            st.markdown(message["content"])
            if message.get("tool"):
                st.markdown(f'<div class="tool-badge">⚙️ Tool used: {message["tool"]}</div>', unsafe_allow_html=True)

    # 2. Chat Input
    user_input = st.chat_input("Ask about sales, discounts, or cannibalization...")
    
    # 3. Determine the prompt
    prompt = None
    if st.session_state.pending_prompt:
        prompt = st.session_state.pending_prompt
        st.session_state.pending_prompt = None
    elif user_input:
        prompt = user_input

    # 4. Process the prompt
    if prompt:
        # Append and render user message immediately
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)
        
        # Render assistant response
        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("Analyzing data..."):
                try:
                    response = requests.post(API_URL, json={"question": prompt}, timeout=60)
                    
                    # Safely parse JSON (handles Render 502 bad gateway HTML pages)
                    try:
                        data = response.json()
                    except requests.exceptions.JSONDecodeError:
                        st.error("API returned an invalid response. It might be starting up. Please try again.")
                        st.stop()
                    
                    if response.status_code == 200:
                        st.markdown(data["answer"])
                        if data.get("tool_called"):
                            st.markdown(f'<div class="tool-badge">⚙️ Tool used: {data["tool_called"]}</div>', unsafe_allow_html=True)
                            st.session_state.messages.append({"role": "assistant", "content": data["answer"], "tool": data["tool_called"]})
                        else:
                            st.session_state.messages.append({"role": "assistant", "content": data["answer"]})
                    else:
                        st.error(f"API Error: {data.get('detail', 'Unknown error occurred')}")
                        
                except requests.exceptions.ConnectionError:
                    st.error("Could not connect to the API. Please check if the backend is running.")
                except requests.exceptions.Timeout:
                    st.error("The API request timed out. The backend might be waking up from sleep. Please try again in a moment.")
        
        # Rerun to update the chat history cleanly without duplicating the current message
        st.rerun()

# =============================================================================
# TAB 2: THE DATA LAB
# =============================================================================
with tab_lab:
    st.write("")
    st.markdown("### Welcome to the Data Lab. Let's find out how grocery stores make money.")
    st.markdown("This dataset contains 2.6 million purchases. We built tools to analyze it. Here is how they work—explained for a high schooler.")
    
    sub_tab1, sub_tab2, sub_tab3, sub_tab4, sub_tab5 = st.tabs([
        "📦 The Dataset", "📉 Elasticity", "🦈 Cannibalization", "📖 Glossary", "🧮 The Math"
    ])
    
    # --- Sub-tab 1: The Dataset ---
    with sub_tab1:
        st.write("")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("Total Purchases", "2.6 Million")
            st.metric("Unique Products", "92,353")
            st.metric("Households Tracked", "2,500")
            st.metric("Stores", "582")
        with col2:
            st.markdown("""
            <div class="fun-card">
                <h3>What does a row of data look like?</h3>
                <p class="analogy-text">Imagine you followed 2,500 families to the grocery store for two years. You wrote down every single item they bought, whether it was on sale, and how much they paid.</p>
                <p class="analogy-text">Here is exactly what one row of our raw dataset looks like:</p>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("**Raw Data Preview:**")
        raw_data = {
            "household_key": [2375, 2375, 1287],
            "BASKET_ID": [26984851472, 26984851472, 26985336468],
            "DAY": [1, 1, 1],
            "PRODUCT_ID": [1004906, 1033142, 5978648],
            "QUANTITY": [1, 1, 1],
            "SALES_VALUE": [1.39, 3.78, 0.00],
            "RETAIL_DISC": [-0.60, -1.00, 0.00],
            "WEEK_NO": [1, 1, 1]
        }
        st.dataframe(pd.DataFrame(raw_data), use_container_width=True)
        
        st.info("**The 'Gotcha' Data:** Notice the 40lb box of bananas (Product 201704) in this dataset? The data says `quantity=1`. If we tried to do elasticity math on that, we might think the bananas cost $30 each! It's actually a wholesale box. Our agent knows this and refuses to do math on bulk items.")

    # --- Sub-tab 2: Elasticity ---
    with sub_tab2:
        st.write("")
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown("""
            <div class="fun-card">
                <h3>What is Elasticity?</h3>
                <p class="analogy-text">Think of a chocolate bar. If it's $2, maybe you buy 2 of them a week. If it goes on sale for $1, maybe you buy 4. That means your demand is <b>elastic</b> (sensitive to price).</p>
                <p class="analogy-text">But what about toilet paper? You don't buy 10 packs just because it's 10% off. You buy the same amount. That demand is <b>inelastic</b>.</p>
                <p class="analogy-text">If a product is inelastic, a discount <b>loses the store money</b>. If it's elastic, a discount can make money.</p>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            st.markdown("##### 🕹️ Interactive Simulation")
            st.markdown("Move the slider to see what happens to a product with **Elasticity = -2** (a very sensitive product).")
            discount = st.slider("Discount Percentage (%)", min_value=0, max_value=50, value=20, step=5)
            
            volume_increase = discount * 2
            normal_margin = 30
            new_margin = normal_margin - discount
            
            if new_margin > 0:
                st.success(f"If you give a **{discount}%** discount, your volume goes up by **{volume_increase}%**, but your profit margin drops from 30% to **{new_margin}%**.")
            else:
                st.error(f"A {discount}% discount completely wipes out your 30% margin! You would be selling at a loss. Our AI agent would refuse to recommend this.")
            
            # New Feature: Plotly Revenue Chart
            st.markdown("---")
            st.markdown("**Revenue Impact:** Notice how revenue peaks and then crashes as discounts get too deep.")
            
            discounts_x = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
            # Simulate revenue (Base Price = $10, Base Qty = 100)
            revenues_y = []
            for d in discounts_x:
                price = 10 * (1 - d/100)
                qty = 100 * (1 + (d * 0.02 * 2)) # 2% volume increase per 1% discount (Elasticity -2)
                revenues_y.append(price * qty)
                
            fig = go.Figure(data=go.Scatter(x=discounts_x, y=revenues_y, mode='lines+markers', line=dict(color='#4F46E5', width=3)))
            fig.update_layout(
                title="Store Revenue vs Discount Depth",
                xaxis_title="Discount (%)",
                yaxis_title="Total Revenue ($)",
                margin=dict(l=0, r=0, t=30, b=0),
                height=250
            )
            st.plotly_chart(fig, use_container_width=True)

    # --- Sub-tab 3: Cannibalization ---
    with sub_tab3:
        st.write("")
        st.markdown("""
        <div class="fun-card">
            <h3>What is Cannibalization?</h3>
            <p class="analogy-text">Imagine you have two siblings: Apple and Orange. If you give Apple a new toy, does Orange play with it? No. But what if you put Apple on sale?</p>
            <p class="analogy-text"><b>Cannibalization</b> happens when you put Product A (Strawberries) on sale, and it steals sales from Product B (the blueberries right next to it), instead of bringing in new customers.</p>
            <p class="analogy-text">The store looks like a hero because Strawberry sales are up. But Blueberry sales are down. The store's total revenue didn't grow—they just shifted customers from one product to another.</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            <div class="fun-card" style="border-left: 4px solid #EF4444;">
                <h4>The Wrong Way (Naive)</h4>
                <p class="analogy-text">"Strawberry sales went up 68% during the promo! But Blueberry sales went down 12%. So the promo stole 12% of Blueberry sales!"</p>
                <p class="analogy-text" style="color: #EF4444; font-weight: bold;">Why it's wrong: It ignores the season. Maybe it was just strawberry season, and blueberry season ended. It's not cannibalization; it's just the weather.</p>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            st.markdown("""
            <div class="fun-card" style="border-left: 4px solid #10B981;">
                <h4>The Right Way (Difference-in-Differences)</h4>
                <p class="analogy-text">We compare Blueberry's drop to a <b>Control Product</b> (e.g., raspberries) that we didn't promote.</p>
                <p class="analogy-text" style="color: #10B981; font-weight: bold;">If raspberries dropped by 10%, and blueberries dropped by 12%, the *true* cannibalization is only 2%. The rest was just the season.</p>
            </div>
            """, unsafe_allow_html=True)

    # --- Sub-tab 4: Glossary ---
    with sub_tab4:
        st.write("")
        st.markdown("### 📖 Interview Glossary")
        st.markdown("If you get asked a term in an interview, this is how you explain it simply.")
        
        with st.expander("What is a Confidence Interval (CI)?"):
            st.write("A range of values that likely contains the true number. If our elasticity is -0.7 with a 95% CI of [-0.8, -0.6], it means we are 95% sure the true elasticity is between -0.8 and -0.6. If the CI crosses zero (e.g., [-0.2, 0.1]), it means the price effect is statistically indistinguishable from zero.")
        with st.expander("What is p-value?"):
            st.write("The probability of seeing these results if there was actually no effect. If the p-value is < 0.05 (5%), we usually say the result is 'statistically significant'.")
        with st.expander("What is CAGR?"):
            st.write("Compound Annual Growth Rate. The average yearly growth rate of a metric over a period of time, assuming it grew at a steady rate.")
        with st.expander("What is Covariance Matrix?"):
            st.write("A grid of numbers that shows how different variables move together. We check the diagonal of this matrix (the variances). If a variance is negative (which is mathematically impossible but happens due to floating-point errors), it means the regression failed.")

    # --- Sub-tab 5: The Math ---
    with sub_tab5:
        st.write("")
        st.markdown("### 🧮 The Underlying Mathematics")
        st.markdown("This is the actual math running under the hood in the backend tools. Good to know if you are asked for technical depth.")
        
        st.markdown("#### 1. Elasticity")
        st.latex(r"Elasticity = \frac{\% \Delta \text{Quantity}}{\% \Delta \text{Price}}")
        st.write("We calculate this using a log-log Ordinary Least Squares (OLS) regression: `log(quantity) ~ log(price)` with week and store fixed effects.")
        
        st.markdown("#### 2. Difference-in-Differences (Cannibalization)")
        st.latex(r"DiD = (B_{during} - B_{baseline}) - (C_{during} - C_{baseline})")
        st.write("Where B is the neighbor product and C is the unaffected control product.")
        
        st.markdown("#### 3. The Continuous-Depth Regression")
        st.latex(r"\log(B\_qty) = \alpha + \beta_1(A\_discount) + \beta_2(B\_discount) + \gamma(week) + \epsilon")
        st.write("Because the store runs category-wide promos, binary 'yes/no' promo flags fail. We regress the neighbor's quantity on the actual discount depth of both products, controlling for week fixed effects to absorb seasonality.")