"""The web layer: the viewer over HTTP, with FastAPI on uvicorn.

The outermost layer. It may import the services and the core; nothing inside
may import it. FastAPI's `Depends` is used here and only here.
"""
