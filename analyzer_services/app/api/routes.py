from fastapi import APIRouter, HTTPException,WebSocket,WebSocketDisconnect,Request
from langchain_core.messages import HumanMessage

from analyzer_services.app.models.schemas import AnalysisRequest
from analyzer_services.app.process.Tasks_analyzer import run_oracle_analysis
from analyzer_services.app.process.ConnectionManager import manager
import uuid
import asyncio

router = APIRouter(prefix="/impact", tags=["Impact"])

@router.post("/respond/{thread_id}")
async def respond_to_interrupt(thread_id: str, response: str, request: Request):
    oracle_app = request.app.state.oracle_graph
    config = {"configurable": {"thread_id": thread_id}}
    inputs = {"messages": [HumanMessage(content=response)]}

    # Reanudar el flujo asincrónicamente
    asyncio.create_task(run_oracle_analysis(thread_id, response, oracle_app, resume=True))

    return {"thread_id": thread_id, "status": "resumed"}


@router.post("/analyze")
async def start_analysis(request: AnalysisRequest,http_request: Request):
##async def start_analysis(request: AnalysisRequest, background_tasks: BackgroundTasks):
    # GUARDRAIL: Filtro de dominio rápido (Regex/Keywords)

    oracle_app = http_request.app.state.oracle_graph
     
    thread_id = f"oracle_project_{uuid.uuid4().hex[:8]}"
    
    # Lanzar el proceso de los 4 agentes sin bloquear la API
    ##background_tasks.add_task(run_oracle_analysis, thread_id, request.query)
    asyncio.create_task(
        run_oracle_analysis(thread_id, request.query,oracle_app)
    )

    return {"thread_id": thread_id, "message": "Análisis en curso..."}

@router.websocket("/ws/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    await manager.connect(websocket, thread_id)
    try:
        while True:
            #await websocket.receive_text() # Mantener conexión viva
           await websocket.receive_text() 
    except WebSocketDisconnect:
        manager.disconnect(thread_id)
        
@router.websocket("/test-ws")
async def test_websocket(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"msg": "Conexión exitosa"})
    await websocket.close()        