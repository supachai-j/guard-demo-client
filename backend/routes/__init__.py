"""Route modules — each FastAPI router is registered on the app in main.py.

Files in this directory exist to keep main.py from being a 2500-line god
module. Adding a new endpoint? Drop it in the route file whose URL prefix
already matches, or create a new one and `app.include_router(...)` it in
main.py.
"""
