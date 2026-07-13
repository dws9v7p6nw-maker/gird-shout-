# Self-contained static-site server. No dashboard "Start Command" needed —
# the CMD below is baked in, sidestepping Render's Start Command field entirely
# (the field that caused "Exited with status 127: command not found").
FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD ["python", "serve.py"]
