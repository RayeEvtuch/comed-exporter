FROM python:3.8-slim

RUN python -m pip install requests pytz prometheus_client

COPY app.py .

CMD [ "python", "app.py" ]
