

### This is a server that is paired with Tampermonkey Addon that by pressing the button sends data on the meme, this server simply writes data to the file.

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os, logging
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI()

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
	exc_str = f'{exc}'.replace('\n', ' ').replace('   ', ' ')
	logging.error(f"{request}: {exc_str}")
	content = {'status_code': 10422, 'message': exc_str, 'data': None}
	return JSONResponse(content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

class FileContent(BaseModel):
    datepost: str
    datecopy: str
    content: str
    source: str

prev_link = ""
prev_channel = ""

@app.post("/add", status_code=201)
async def add_line_to_file(data: FileContent):
    global prev_link, prev_channel
    print(data)
    if prev_link == data.content and prev_channel == data.source:
        raise HTTPException(status_code=409, detail=f"Previously added")

    try:
        with open("/mnt/memoryConflux11/alex/preset", "a", encoding="utf-8") as f:
            f.write(f"{data.datepost}|||{data.datecopy}|||{data.content}|||{data.source}\n")
        
        prev_link = data.content
        prev_channel = data.source
        return {"status": "success", "message": f"Line added"}
    
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"Error writing to file: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)