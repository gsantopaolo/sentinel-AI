#region imports
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
import logging

#endregion

logger = logging.getLogger("uvicorn.error")

class CustomErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except RequestValidationError as exc:
            logger.error(f"Validation error: {exc}")
            return JSONResponse(
                status_code=400,
                content={"detail": exc.errors()},
            )
        except HTTPException as exc:
            logger.error(f"HTTP error: {exc}")
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
        except Exception as exc:
            logger.exception(f"Unhandled error: {exc}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"},
            )
