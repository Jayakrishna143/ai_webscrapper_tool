# app.py
import streamlit as st
import asyncio
import threading
import traceback
import queue
import time
from agent_loop import run_agent

st.set_page_config(page_title="Self-Healing Scraper", layout="wide")

st.title("🕸️ Self-Healing ReAct Scraper")
st.markdown(
    "Enter a target URL and what you want to extract. The agent will write its own code, test it, fix it if it breaks, and return the data.")

target_url = st.text_input("Target URL", value="https://quotes.toscrape.com/")
extraction_goal = st.text_area(
    "Extraction Goal",
    value="Extract ALL quotes on the first page . For each quote, return a dictionary with 'text' and 'author'. Do not stop until you have all 10 entries in the JSON array."
)

if st.button("Run Extraction", type="primary"):

    st.divider()
    st.subheader("Process Logs")

    log_container = st.empty()
    logs = []
    log_queue = queue.Queue()  # thread puts here, main thread reads from here

    def st_log_callback(message):
        logs.append(str(message))
        log_queue.put(str(message))  # no Streamlit calls, just queue it

    st.subheader("Final Output")
    output_container = st.empty()

    result_container = {}
    error_container = {}

    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_container["data"] = loop.run_until_complete(
                run_agent(target_url, extraction_goal, st_log_callback)
            )
        except Exception:
            error_container["traceback"] = traceback.format_exc()
        finally:
            loop.close()

    thread = threading.Thread(target=run_in_thread)
    thread.start()

    # main thread stays here, drains queue and updates UI while thread runs
    while thread.is_alive():
        while not log_queue.empty():
            log_queue.get()
            log_container.code("\n".join(logs), language="text")
        time.sleep(0.2)

    # drain anything remaining after thread finishes
    while not log_queue.empty():
        log_queue.get()
    log_container.code("\n".join(logs), language="text")

    thread.join()

    if "traceback" in error_container:
        st.error("An error occurred:")
        st.code(error_container["traceback"], language="text")
    elif "data" in result_container:
        final_data, final_code = result_container["data"]
        st.success("Extraction Complete!")
        st.markdown("### Extracted Data (JSON)")
        output_container.text(final_data)
        with st.expander("View Final Executed Python Code"):
            st.code(final_code, language="python")
    else:
        st.error("Agent returned no data and no error. This shouldn't happen.")