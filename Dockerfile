FROM python:3.12-slim 
WORKDIR /app 
RUN pip install --no-cache-dir cryptography==43.0.1 flask==3.0.0 
COPY . . 
CMD ["python", "app.py"] 
