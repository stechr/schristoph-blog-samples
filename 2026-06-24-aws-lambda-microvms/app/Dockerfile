FROM public.ecr.aws/lambda/microvms:al2023-minimal

RUN dnf install -y python3 python3-pip && dnf clean all

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app.py .

# Workspace where executed code can read/write files (used by the isolation demo).
RUN mkdir -p /workspace

# 8080 = application traffic (routed by the proxy); 9000 = lifecycle hooks.
EXPOSE 8080 9000

# Single process serves the API (8080) + hooks (9000) so the in-memory session
# namespace is shared across requests and preserved across suspend/resume.
CMD ["python3", "app.py"]
