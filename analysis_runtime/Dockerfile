FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /runtime
RUN pip install --no-cache-dir pandas numpy scipy matplotlib statsmodels xarray pyarrow google-cloud-storage
COPY safety.py runner.py ./
RUN useradd --create-home --uid 10001 analysis && mkdir -p /workspace/input /workspace/output && chown -R analysis /workspace
USER analysis
ENTRYPOINT ["python", "runner.py"]
