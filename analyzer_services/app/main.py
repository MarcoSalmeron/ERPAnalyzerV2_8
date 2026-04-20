from fastapi import FastAPI, APIRouter, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
import uuid
from analyzer_services.app.api.routes import router
import os
from fastapi.staticfiles import StaticFiles
import asyncio
import sys
from contextlib import asynccontextmanager
from agents.supervisor import team
from langgraph.checkpoint.memory import MemorySaver
import os
from pathlib import Path

REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"
if not os.path.exists(REPORTS_DIR):
    os.makedirs(REPORTS_DIR)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---

    print("🚀 Inicializando LangGraph")
    memory = MemorySaver()
    app.state.oracle_graph = team.compile(checkpointer=memory)
    print("✅ LangGraph inicializado")
    yield
    # --- SHUTDOWN ---
    print("🛑 Cerrando aplicación")


services = FastAPI(
    title="Oracle Cloud InsightReadinesss API",
    description="API para el análisis de Oracle Cloud Readiness",
    version="1.0.0",
    lifespan=lifespan,
)

services.mount("/static/reports", StaticFiles(directory=REPORTS_DIR), name="reports")
services.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])
# Incluir rutas de la API
services.include_router(router)

router = APIRouter()

# --- Endpoint raíz ---
@services.get("/")
def read_root():
    return {"message": "API de Oracle Cloud Readiness"}

# --- Iniciar análisis ---
@router.post("/analyze")
async def start_analysis(query: str):
    thread_id = f"oracle_{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    inputs = {"messages": [HumanMessage(content=query)]}

    asyncio.create_task(run_flow(inputs, config, thread_id))
    return {"thread_id": thread_id, "status": "started"}

# --- Reanudar tras interrupción ---
@router.post("/resume/{thread_id}")
async def resume_analysis(thread_id: str, user_response: str):
    config = {"configurable": {"thread_id": thread_id}}
    inputs = {"messages": [HumanMessage(content=user_response)]}

    asyncio.create_task(run_flow(inputs, config, thread_id))
    return {"thread_id": thread_id, "status": "resumed"}

# --- WebSocket para eventos ---
@router.websocket("/ws/{thread_id}")
async def ws_endpoint(websocket: WebSocket, thread_id: str):
    await websocket.accept()
    services.state.connections[thread_id] = websocket
    await websocket.send_json({"status": "connected", "thread_id": thread_id})


# --- Función auxiliar para ejecutar flujo y enviar eventos ---
async def run_flow(inputs, config, thread_id):
    app = services.state.oracle_graph
    websocket = services.state.connections.get(thread_id)

    async for event in app.astream(inputs, config=config, stream_mode="values"):
        if websocket:
            # Mensajes normales
            if "messages" in event:
                last_msg = event["messages"][-1].content
                await websocket.send_json({"type": "message", "content": last_msg})

            # Interrupción HITL
            if event.get("interrupt"):
                pregunta = event["interrupt"]
                await websocket.send_json({"type": "interrupt", "question": pregunta})
                break  # pausa hasta que llegue resume

    # Verificar estado final
    state = await app.aget_state(config)
    if websocket:
        if not state.next:  # flujo terminado
            final_messages = state.values.get("messages", [])
            final_content = final_messages[-1].content if final_messages else "Proceso finalizado."
            await websocket.send_json({"type": "finished", "content": final_content})


# --- Inicializar diccionario de conexiones ---
services.state.connections = {}

services.include_router(router)
