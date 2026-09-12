FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORTAL_SECURE_COOKIE=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Explicit copies prevent local databases, documents and credentials entering the image.
COPY server.py cloud_start.py manage.py BRANDING_NOTICE.txt ./
COPY static ./static
EXPOSE 8080
CMD ["python", "cloud_start.py"]
