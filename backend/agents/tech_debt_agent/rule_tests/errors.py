# ruff: noqa
import logging
import traceback

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from flask import jsonify

logger = logging.getLogger(__name__)


def swallowed(fn):
    try:
        fn()
    # ruleid: except-pass-tragado
    except:
        pass
    try:
        fn()
    # ruleid: except-pass-tragado
    except Exception:
        pass
    try:
        fn()
    # ok: except-pass-tragado
    except KeyError:
        pass
    try:
        fn()
    # ok: except-pass-tragado
    except Exception:
        logger.exception("fallo")


def printed(fn):
    try:
        fn()
    # ruleid: except-print-tragado
    except Exception as e:
        print(e)
    try:
        fn()
    # ok: except-print-tragado
    except Exception as e:
        logger.error(e)


def exposed(fn):
    try:
        fn()
    except Exception as e:
        # ruleid: error-expuesto-en-respuesta
        return {"error": str(e)}
    try:
        fn()
    except Exception as e:
        # ruleid: error-expuesto-en-respuesta
        return {"error": str(e)}, 500
    try:
        fn()
    except Exception as e:
        # ruleid: error-expuesto-en-respuesta
        raise HTTPException(status_code=500, detail=f"fallo: {e}")
    try:
        fn()
    except Exception as e:
        # ruleid: error-expuesto-en-respuesta
        raise HTTPException(status_code=500, detail=str(e))
    try:
        fn()
    except Exception as e:
        # ruleid: error-expuesto-en-respuesta
        return jsonify(error=str(e))
    try:
        fn()
    except Exception as e:
        # ruleid: error-expuesto-en-respuesta
        return jsonify({"error": str(e)})
    try:
        fn()
    except Exception as e:
        # ruleid: error-expuesto-en-respuesta
        return JSONResponse(status_code=500, content={"error": str(e)})
    try:
        fn()
    except Exception as e:
        logger.exception(e)
        # ok: error-expuesto-en-respuesta
        raise HTTPException(status_code=500, detail="Error interno")
    # ok: error-expuesto-en-respuesta
    return {"error": str(fn)}


def tb():
    # ruleid: traceback-en-respuesta
    return {"trace": traceback.format_exc()}
    # ok: traceback-en-respuesta
    logger.error(traceback.format_exc())


# ruleid: flask-debug-activo
app.run(debug=True)
# ok: flask-debug-activo
app.run(debug=False)
