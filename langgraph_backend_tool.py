from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool
from dotenv import load_dotenv
import sqlite3
import requests
import os

load_dotenv()

# -------------------
# 1. LLM
# -------------------
llm = ChatGoogleGenerativeAI(model = "gemini-2.5-flash")

# -------------------
# 2. Tools
# -------------------
# Tools
search_tool = DuckDuckGoSearchRun(region="us-en")

@tool
def calculator(first_num: float, second_num: float, operation: str) -> dict:
    """
    Perform a basic arithmetic operation on two numbers.
    Supported operations: add, sub, mul, div
    """
    try:
        if operation == "add":
            result = first_num + second_num
        elif operation == "sub":
            result = first_num - second_num
        elif operation == "mul":
            result = first_num * second_num
        elif operation == "div":
            if second_num == 0:
                return {"error": "Division by zero is not allowed"}
            result = first_num / second_num
        else:
            return {"error": f"Unsupported operation '{operation}'"}
        
        return {"first_num": first_num, "second_num": second_num, "operation": operation, "result": result}
    except Exception as e:
        return {"error": str(e)}
    
    
@tool
def get_stock_price(symbol : str) -> dict:
    """
    Fetch latest stock price for a given symbol (e.g. 'AAPL', 'TSLA') 
    using Alpha Vantage with API key in the URL.
    """
    
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey=L68PTEPYJV8XFY26"
    response = requests.get(url)
    return response.json()


@tool
def get_weather(city : str) -> dict:
     """
     Get current weather for a city using OpenWeatherMap.
city (str): City name, e.g., "Kolkata".
Returns dict with city, temp (°C), weather, humidity, or 'error'.
    """
     api_key = os.getenv("OPENWEATHER_API_KEY")
     url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
     
     try:
         response = requests.get(url)
         data = response.json()
         
         if data.get("cod") != 200:
            return {"error": data.get("message", "City not found")}
        
         return {
                "city": data["name"],
                "temperature": data["main"]["temp"],
                "weather": data["weather"][0]["description"],
                "humidity": data["main"]["humidity"]
         }
        
     except Exception as e:
         return {"error" : str(e)}   
     
     
@tool
def convert_currency(from_currency: str, to_currency: str, amount: float) -> dict:
    """
    Convert amount from one currency to another using ExchangeRate-API.
    from_currency: 3-letter code, e.g., "USD"
    to_currency: 3-letter code, e.g., "INR"
    amount: numeric value to convert
    Returns dict with from, to, amount, converted_amount, or 'error'
    """
    try:
        api_key = os.getenv("EXCHANGE_API_KEY")
        url = f"https://v6.exchangerate-api.com/v6/{api_key}/pair/{from_currency}/{to_currency}/{amount}"
        response = requests.get(url)
        data = response.json()

        if data.get("result") != "success":
            return {"error": data.get("error-type", "Conversion failed")}

        return {
            "from": from_currency,
            "to": to_currency,
            "amount": amount,
            "converted_amount": data["conversion_result"]
        }

    except Exception as e:
        return {"error": str(e)}

    


tools = [search_tool, calculator, get_stock_price, get_weather, convert_currency]
llm_with_tools = llm.bind_tools(tools) 

# -------------------
# 3. State
# -------------------
class ChatState(TypedDict):
    messages : Annotated[list[BaseMessage], add_messages]
    
# -------------------
# 4. Nodes
# -------------------
def chat_node(state : ChatState):
    """LLM node that may answer or request a tool call."""
    messages = state["messages"]
    response = llm_with_tools.invoke(messages)
    return {'messages' : [response]}

tool_node = ToolNode(tools) 

# -------------------
# 5. Checkpointer
# -------------------
conn = sqlite3.connect(database="chatbot.db", check_same_thread=False)
checkpointer = SqliteSaver(conn=conn)

# -------------------
# 6. Graph
# -------------------
graph = StateGraph(ChatState)

graph.add_node("chat_node", chat_node)
graph.add_node("tools", tool_node)

graph.add_edge(START, "chat_node")

graph.add_conditional_edges("chat_node", tools_condition)
graph.add_edge("tools", "chat_node")

chatbot = graph.compile(checkpointer=checkpointer)

# -------------------
# 7. Helper
# -------------------
def retrieve_all_threads():
    all_threads = set()
    for checkpoint in checkpointer.list(None):
        all_threads.add(checkpoint.config["configurable"]["thread_id"])
    return list(all_threads)