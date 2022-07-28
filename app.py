
from datetime import datetime, timedelta
from time import sleep
from pytz import timezone
import requests
import json
import re

import threading

from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, REGISTRY

COMED_MONTH = re.compile(r'(?<=Date\.UTC\(\d{4},)\d+(?=,\d+,\d+,\d+,\d+\))')


def convert_comed_date(datestring: str):
    # Change from zero-indexed months to one-indexed months
    original_month = COMED_MONTH.findall(datestring)[0]
    real_month = str(int(original_month)+1)
    fixed_datestring = re.sub(
        COMED_MONTH, real_month, datestring)
    # Take the datetime (that isn't actually in UTC)
    # and subtract an hour to when the price takes effect
    timestamp = timezone('US/Central').localize(
        datetime.strptime(
            fixed_datestring,
            'Date.UTC(%Y,%m,%d,%H,%M,%S)')
    ).timestamp()-3600

    return timestamp


class ComEdCollector(object):

    def update_cache(self):
        print('polling')

        # Get the spot prices from ComEd
        spot_price_response = requests.get(
            url='https://hourlypricing.comed.com/api?type=5minutefeed')
        self.spot_price_data = json.loads(spot_price_response.content)

        # Get today's price predictions from ComEd
        price_prediction_response = requests.get(
            url='https://hourlypricing.comed.com/rrtp/ServletFeed?type=daynexttoday')
        # Fix the bad JSON unquoted date strings
        fixed_price_prediction_response = price_prediction_response.content.decode(
        ).replace('Date.UTC', '"Date.UTC').replace('), ', ')", ')
        self.price_prediction_data_today = json.loads(
            fixed_price_prediction_response)

        # Get today's actual prices from ComEd
        price_actual_response = requests.get(
            url='https://hourlypricing.comed.com/rrtp/ServletFeed?type=day')
        # Fix the bad JSON unquoted date strings
        fixed_price_actual_response = price_actual_response.content.decode(
        ).replace('Date.UTC', '"Date.UTC').replace('), ', ')", ')
        self.price_actual_data_today = json.loads(
            fixed_price_actual_response)

    def collect(self):

        # Set up the main metric
        kwh_price = GaugeMetricFamily(
            name='kwh_price',
            documentation='Electricity price in cents per kWh',
            labels=[
                'provider',
                'type',
            ],
        )

        now=datetime.now()
        current_hour=datetime(now.year,now.month,now.day,now.hour).timestamp()
        current_hour_prices=[]

        for spot_price in self.spot_price_data:
            timestamp=int(spot_price['millisUTC'])/1000
            kwh_price.add_sample(
                name='kwh_price',
                labels={
                    'provider': 'comed',
                    'type': 'spot',
                },
                value=spot_price['price'],
                # Convert from milliseconds to seconds
                timestamp=timestamp
            )
            if timestamp > current_hour:
                current_hour_prices.append(float(spot_price['price']))

        if current_hour_prices:
            current_hour_estimate=round(sum(current_hour_prices) / len(current_hour_prices),1)
            for multiplier in range(12):
                kwh_price.add_sample(
                    name='kwh_price',
                    labels={
                        'provider': 'comed',
                        'type': 'actual',
                    },
                    value=current_hour_estimate,
                    timestamp=current_hour+60*5*multiplier
                )

        for price_prediction in self.price_prediction_data_today:
            for multiplier in range(12):
                kwh_price.add_sample(
                    name='kwh_price',
                    labels={
                        'provider': 'comed',
                        'type': 'predicted',
                    },
                    value=price_prediction[1],
                    timestamp=convert_comed_date(price_prediction[0])+60*5*multiplier
                )

        for price_actual in self.price_actual_data_today:
            for multiplier in range(12):
                kwh_price.add_sample(
                    name='kwh_price',
                    labels={
                        'provider': 'comed',
                        'type': 'actual',
                    },
                    value=price_actual[1],
                    timestamp=convert_comed_date(price_actual[0])+60*5*multiplier
                )

        yield kwh_price


comEdCollector = ComEdCollector()
comEdCollector.update_cache()
REGISTRY.register(comEdCollector)

if __name__ == '__main__':
    # Start up the server to expose the metrics.
    start_http_server(8000)
    while True:
        sleep(60*5)
        comEdCollector.update_cache()
