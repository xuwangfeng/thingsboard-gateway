#     Copyright 2025. ThingsBoard
#
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.

import math
from decimal import Decimal, InvalidOperation
from datetime import timezone
from time import time

from asyncua.ua.uatypes import VariantType

from thingsboard_gateway.connectors.opcua.opcua_converter import OpcUaConverter
from thingsboard_gateway.gateway.constants import TELEMETRY_PARAMETER, ATTRIBUTES_PARAMETER, REPORT_STRATEGY_PARAMETER, TIMESERIES_PARAMETER
from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.report_strategy_config import ReportStrategyConfig
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry
from thingsboard_gateway.gateway.statistics.statistics_service import StatisticsService
from thingsboard_gateway.tb_utility.tb_utility import TBUtility

DATA_TYPES = {
    'attributes': ATTRIBUTES_PARAMETER,
    'timeseries': TELEMETRY_PARAMETER
}

VARIANT_TYPE_HANDLERS = {
    VariantType.ExtensionObject: lambda data: str(data),
    VariantType.DateTime: lambda data: data.replace(
        tzinfo=timezone.utc).isoformat() if data.tzinfo is None else data.isoformat(),
    VariantType.StatusCode: lambda data: data.name,
    VariantType.QualifiedName: lambda data: data.to_string(),
    VariantType.NodeId: lambda data: data.to_string(),
    VariantType.ExpandedNodeId: lambda data: data.to_string(),
    VariantType.ByteString: lambda data: data.hex(),
    VariantType.XmlElement: lambda data: data.decode('utf-8'),
    VariantType.Guid: lambda data: str(data),
    VariantType.DiagnosticInfo: lambda data: data.to_string(),
    VariantType.Null: lambda data: None
}

ERROR_MSG_TEMPLATE = "Bad status code: {} for node: {} with description {}"


class OpcUaUplinkConverter(OpcUaConverter):
    def __init__(self, config, logger):
        self._log = logger
        self.__config = config

    def process_datapoint(self, config, val, basic_timestamp, device_report_strategy):
        try:
            error = None
            data = val.Value.Value
            if isinstance(data, list):
                data = [str(item) for item in data]
            else:
                handler = VARIANT_TYPE_HANDLERS.get(val.Value.VariantType, lambda d: d if not hasattr(d, 'to_string') else d.to_string())
                data = handler(data)

            if data is None and val.StatusCode.is_bad():
                data = str.format(ERROR_MSG_TEMPLATE,val.StatusCode.name, val.data_type, val.StatusCode.doc)
                error = True

            timestamp_location = config.get('timestampLocation', 'gateway').lower()
            timestamp = basic_timestamp  # Default timestamp
            if timestamp_location == 'sourcetimestamp' and val.SourceTimestamp is not None:
                timestamp = val.SourceTimestamp.timestamp() * 1000
            elif timestamp_location == 'servertimestamp' and val.ServerTimestamp is not None:
                timestamp = val.ServerTimestamp.timestamp() * 1000

            section = DATA_TYPES[config['section']]
            datapoint_key = TBUtility.convert_key_to_datapoint_key(config['key'], device_report_strategy, config, self._log)

            # 从 self.__config 查找对应的 formula 配置
            formula_config = self.__find_formula_config(config['key'], section)

            if formula_config:
                original_value = val.Value.Value
                # 尝试将原始值转换为数字（如果可以转换的话）
                numeric_value = self.__try_convert_to_number(original_value)
                if numeric_value is not None:
                    calculated_data = self.__apply_formula_if_configured(numeric_value, formula_config)
                    if calculated_data is not None:
                        self._log.info("公式计算: key=%s, 原始值=%s(%s), 计算后=%s",
                                      config['key'], original_value, type(original_value).__name__, calculated_data)
                        data = calculated_data
                else:
                    self._log.debug("无法将值转换为数字，跳过公式计算: %s (类型: %s)",
                                    original_value, type(original_value).__name__)

            if section == TELEMETRY_PARAMETER:
                return TelemetryEntry({datapoint_key: data}, ts=timestamp), error
            elif section == ATTRIBUTES_PARAMETER:
                return {datapoint_key: data}, error
        except Exception as e:
            return None, str(e)

    def convert(self, configs, values) -> ConvertedData:
        StatisticsService.count_connector_message(self._log.name, 'convertersMsgProcessed')
        basic_timestamp = int(time() * 1000)

        try:
            if not isinstance(configs, list):
                configs = [configs]
            if not isinstance(values, list):
                values = [values]

            converted_data = ConvertedData(device_name=self.__config['device_name'], device_type=self.__config['device_type'])

            device_report_strategy = None
            try:
                device_report_strategy = ReportStrategyConfig(self.__config.get(REPORT_STRATEGY_PARAMETER))
            except ValueError as e:
                self._log.trace("Report strategy config is not specified for device %s: %s", self.__config['device_name'], e)

            telemetry_batch = []
            attributes_batch = []

            for config, val in zip(configs, values):
                result, error = self.process_datapoint(config, val, basic_timestamp, device_report_strategy)
                if result is not None:
                    if isinstance(result, TelemetryEntry):
                        telemetry_batch.append(result)
                    elif isinstance(result, dict):
                        attributes_batch.append(result)

            converted_data.add_to_telemetry(telemetry_batch)
            for attr in attributes_batch:
                converted_data.add_to_attributes(attr)

            StatisticsService.count_connector_message(self._log.name, 'convertersAttrProduced', count=converted_data.attributes_datapoints_count)
            StatisticsService.count_connector_message(self._log.name, 'convertersTsProduced', count=converted_data.telemetry_datapoints_count)

            return converted_data
        except Exception as e:
            self._log.exception("Error occurred while converting data: ", exc_info=e)
            StatisticsService.count_connector_message(self._log.name, 'convertersMsgDropped')

    @staticmethod
    def fill_telemetry(results):
        telemetry_batch = []
        for result, error in results:
            if isinstance(result, TelemetryEntry):
                telemetry_batch.append(result)
        return telemetry_batch

    @staticmethod
    def fill_attributes(results):
        attributes_batch = []
        for result, error in results:
            if isinstance(result, dict):
                attributes_batch.append(result)
        return attributes_batch

    def __try_convert_to_number(self, value):
        """
        尝试将值转换为数字类型

        Args:
            value: 原始值

        Returns:
            转换后的数字（int 或 float），如果无法转换则返回 None
        """
        if isinstance(value, (int, float)):
            # 排除布尔类型，因为 bool 是 int 的子类
            if isinstance(value, bool):
                return None
            return value

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            try:
                # 尝试转换为 int
                if '.' not in value and 'e' not in value.lower():
                    return int(value)
                else:
                    return float(value)
            except ValueError:
                return None

        # 其他类型无法转换
        return None

    def __find_formula_config(self, key, section):
        """
        从 self.__config 中查找对应 key 的 formula 配置

        Args:
            key: 数据点 key
            section: TIMESERIES_PARAMETER 或 ATTRIBUTES_PARAMETER

        Returns:
            包含 formula/divider/multiplier 的配置字典，如果没有则返回 None
        """
        # 根据section常量确定配置键
        if section == TELEMETRY_PARAMETER or section == TIMESERIES_PARAMETER:
            config_key = TIMESERIES_PARAMETER
        elif section == ATTRIBUTES_PARAMETER:
            config_key = ATTRIBUTES_PARAMETER
        else:
            self._log.warning("未知的 section 类型: %s", section)
            return None

        config_list = self.__config.get(config_key, [])
        if isinstance(config_list, list):
            for item in config_list:
                if item.get('key') == key:
                    formula_config = {}
                    if item.get('formula'):
                        formula_config['formula'] = item['formula']
                    if item.get('divider'):
                        formula_config['divider'] = item['divider']
                    if item.get('multiplier'):
                        formula_config['multiplier'] = item['multiplier']
                    if formula_config:
                        return formula_config
        return None

    def __apply_formula_if_configured(self, value, config):
        """
        应用公式计算（如果配置中指定）

        Args:
            value: 原始值
            config: 包含 formula/divider/multiplier 的配置

        Returns:
            处理后的值
        """
        original_value = value

        if config.get('formula'):
            try:
                formula = config['formula']
                expression = formula.replace('{原始值}', str(value)).replace('×', '*').replace('÷', '/')

                # 宽松模式：提供安全的数学函数，但仍禁用 __builtins__ 防止执行危险代码
                eval_globals = {
                    "__builtins__": {},
                    "nan": float('nan'),
                    "inf": float('inf'),
                    "abs": abs,
                    "min": min,
                    "max": max,
                    "round": round,
                    "pow": pow,
                    "sqrt": math.sqrt,
                    "ceil": math.ceil,
                    "floor": math.floor,
                }

                calculated_value = eval(expression, eval_globals)
                value = Decimal(str(calculated_value))

                self._log.debug("Applied formula '%s' to value %s, result: %s",
                                formula, original_value, value)
            except Exception as e:
                self._log.warning("Failed to apply formula '%s': %s. Using original value.",
                                  config.get('formula'), e)
                value = original_value

        elif config.get('divider'):
            try:
                value = Decimal(str(value)) / Decimal(str(config['divider']))
            except (InvalidOperation, ValueError, TypeError) as e:
                self._log.warning("Failed to apply divider with Decimal precision, falling back to float: %s", e)
                try:
                    value = Decimal(str(float(value) / float(config['divider'])))
                except (TypeError, ZeroDivisionError) as e:
                    self._log.warning("Failed to apply divider: %s. Using original value.", e)
                    value = original_value

        elif config.get('multiplier'):
            try:
                value = Decimal(str(value)) * Decimal(str(config['multiplier']))
            except (InvalidOperation, ValueError, TypeError) as e:
                self._log.warning("Failed to apply multiplier with Decimal precision, falling back to float: %s", e)
                try:
                    value = Decimal(str(value * config['multiplier']))
                except TypeError as e:
                    self._log.warning("Failed to apply multiplier: %s. Using original value.", e)
                    value = original_value

        # 应用小数精度：如果超过2位小数则截断，否则保留原始值
        if isinstance(value, Decimal):
            decimal_tuple = value.as_tuple()
            if decimal_tuple.exponent < -2:  # 超过2位小数
                value = value.quantize(Decimal('0.00'), rounding='ROUND_DOWN')
            value = float(value)
        elif isinstance(value, float):
            decimal_value = Decimal(str(value))
            decimal_tuple = decimal_value.as_tuple()
            if decimal_tuple.exponent < -2:  # 超过2位小数
                value = float(decimal_value.quantize(Decimal('0.00'), rounding='ROUND_DOWN'))
        elif isinstance(value, int):
            value = float(value)

        return value
