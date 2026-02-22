from __future__ import annotations

from collections.abc import Callable
import logging
import socket
from threading import Lock, Thread
import time

from .config import Config
from .ctrl_enum import EnumDevice
from .dao import STATUS_ATTR, AirCon, AirConStatus, Room, Sensor, get_device_by_aircon
from .decoder import BaseResult, decoder
from .display import display
from .param import (
    AirConControlParam,
    AirConQueryStatusParam,
    HandShakeParam,
    HeartbeatParam,
    Param,
    Sensor2InfoParam,
    HDQueryStatusParam,
    HDQueryInfoParam,
    HDBaseControlParam,
)

_LOGGER = logging.getLogger(__name__)


def _log(s: str):
    s = str(s)
    for i in s.split("\n"):
        _LOGGER.debug(i)


class SocketClient:
    def __init__(self, host: str, port: int, service: Service, config: Config):
        self._host = host
        self._port = port
        self._config = config
        self._locker = Lock()
        self._s = None
        while not self.do_connect():
            time.sleep(3)
        self._ready = True
        self._recv_thread = RecvThread(self, service)
        self._recv_thread.start()

    def destroy(self):
        self._ready = False
        self._recv_thread.terminate()
        self._s.close()

    def do_connect(self):
        self._s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._s.connect((self._host, self._port))
        except OSError as exc:
            _log("connected error")
            _log(str(exc))
            return False
        else:
            _log("connected")
            return True

    def send(self, p: Param):
        self._locker.acquire()
        _log("send hex: 0x" + p.to_string(self._config).hex())
        _log("\033[31msend:\033[0m")
        _log(display(p))
        done = False
        while not done:
            try:
                self._s.sendall(p.to_string(self._config))
                done = True
            except Exception:
                time.sleep(3)
                self.do_connect()
        self._locker.release()

    def recv(self) -> (list[BaseResult], bytes):
        res = []
        done = False
        data = None

        while not done:
            try:
                data = self._s.recv(1024)
                done = True
            except Exception:
                if not self._ready:
                    return [], None
                time.sleep(3)
                self.do_connect()
        if data is not None:
            _log("recv hex: 0x" + data.hex())
        while data:
            try:
                r, b = decoder(data, self._config)
                res.append(r)
                data = b
            except Exception as e:
                _log(e)
                data = None
        return res


class RecvThread(Thread):
    def __init__(self, sock: SocketClient, service: Service):
        super().__init__()
        self._sock = sock
        self._service = service
        self._locker = Lock()
        self._running = True

    def terminate(self):
        self._running = False

    def run(self) -> None:
        while self._running:
            res = self._sock.recv()
            for i in res:
                _log("\033[31mrecv:\033[0m")
                _log(display(i))
                self._locker.acquire()
                try:
                    if i is not None:
                        i.do(self._service)
                except Exception as e:
                    _log(e)
                self._locker.release()


class HeartBeatThread(Thread):
    def __init__(self, service: Service):
        super().__init__()
        self.service = service
        self._running = True

    def terminate(self):
        self._running = False

    def run(self) -> None:
        super().run()
        time.sleep(30)
        cnt = 0
        while self._running:
            self.service.send_msg(HeartbeatParam())
            cnt += 1
            if cnt == self.service.get_scan_interval():
                _log("poll_status")
                cnt = 0
                self.service.poll_status()

            time.sleep(60)


class Service:
    def __init__(self):
        self._socket_client: SocketClient = None
        self._rooms: list[Room] = None
        self._aircons: list[AirCon] = None
        self._new_aircons: list[AirCon] = None
        self._bathrooms: list[AirCon] = None
        self._hds: list[HD] = None  # 添加HD设备列表初始化
        self._ready: bool = False
        self._none_stat_dev_cnt: int = 0
        self._status_hook: list[(AirCon, Callable)] = []
        self._sensor_hook: list[(str, Callable)] = []
        self._hd_hook: list[(HD, Callable)] = []  # 添加HD状态钩子初始化
        self._heartbeat_thread = None
        self._sensors: list[Sensor] = []
        self._scan_interval: int = 5
        self.state_change_listener: Callable[[], None] | None = None

    def init(self, host: str, port: int, scan_interval: int, config: Config) -> None:
        if self._ready:
            return
        self._scan_interval = scan_interval
        self._socket_client = SocketClient(host, port, self, config)
        self._socket_client.send(HandShakeParam())
        self._heartbeat_thread = HeartBeatThread(self)
        self._heartbeat_thread.start()
        
        # 添加超时机制避免无限等待
        timeout = 60  # 60秒超时
        elapsed = 0
        
        # 分别检查各个设备类型的初始化状态
        aircon_initialized = False
        new_aircon_initialized = False
        bathroom_initialized = False
        rooms_initialized = False
        hd_initialized = False  # 添加HD设备初始化标志
        
        while elapsed < timeout:
            # 检查房间信息是否已获取
            if not rooms_initialized and self._rooms is not None:
                rooms_initialized = True
                _LOGGER.info("[Service] 房间信息初始化完成")
            
            # 检查传统空调是否已获取
            if not aircon_initialized and self._aircons is not None:
                aircon_initialized = True
                _LOGGER.info("[Service] 传统空调设备初始化完成")
            
            # 检查新风空调是否已获取
            if not new_aircon_initialized and self._new_aircons is not None:
                new_aircon_initialized = True
                _LOGGER.info("[Service] 新风空调设备初始化完成")
            
            # 检查浴室空调是否已获取
            if not bathroom_initialized and self._bathrooms is not None:
                bathroom_initialized = True
                _LOGGER.info("[Service] 浴室空调设备初始化完成")
            
            # 检查HD设备是否已获取
            if not hd_initialized and self._hds is not None:
                hd_initialized = True
                _LOGGER.info("[Service] HD设备初始化完成")
            
            # 如果关键设备都已初始化，则退出等待
            if (
                rooms_initialized 
                and aircon_initialized 
                and new_aircon_initialized 
                and bathroom_initialized
                and hd_initialized
            ):
                _LOGGER.info("[Service] 房间及所有设备信息初始化完成，准备就绪")
                break
                
            time.sleep(1)
            elapsed += 1
            
        # 超时处理
        if elapsed >= timeout:
            _LOGGER.warning("[Service] 设备初始化超时，未获取到的设备将使用默认空列表继续")
            if self._rooms is None:
                self._rooms = []
                _LOGGER.warning("[Service] 房间信息初始化超时，使用空列表")
            if self._aircons is None:
                self._aircons = []
                _LOGGER.warning("[Service] 传统空调初始化超时，使用空列表")
            if self._new_aircons is None:
                self._new_aircons = []
                _LOGGER.warning("[Service] 新风空调初始化超时，使用空列表")
            if self._bathrooms is None:
                self._bathrooms = []
                _LOGGER.warning("[Service] 浴室空调初始化超时，使用空列表")
            if self._hds is None:
                self._hds = []
                _LOGGER.warning("[Service] HD设备初始化超时，使用空列表")
        
        # 安全地设置设备别名，添加空值检查
        try:
            if self._aircons is not None:
                for i in self._aircons:
                    for j in self._rooms:
                        if i.room_id == j.id:
                            i.alias = j.alias
                            if i.unit_id:
                                i.alias += str(i.unit_id)
            if self._new_aircons is not None:
                for i in self._new_aircons:
                    for j in self._rooms:
                        if i.room_id == j.id:
                            i.alias = j.alias
                            if i.unit_id:
                                i.alias += str(i.unit_id)
            if self._bathrooms is not None:
                for i in self._bathrooms:
                    for j in self._rooms:
                        if i.room_id == j.id:
                            i.alias = j.alias
                            if i.unit_id:
                                i.alias += str(i.unit_id)
            if self._hds is not None:
                for i in self._hds:
                    for j in self._rooms:
                        if i.room_id == j.id:
                            i.alias = j.alias
                            if i.unit_id:
                                i.alias += str(i.unit_id)
        except Exception as e:
            _LOGGER.error(f"[Service] 设置设备别名时出错: {e}")
        
        #_log(f"[HD] 初始化完成，共发现 {len(self._hds)} 个HD设备")        
        self._ready = True
        _log("[Service] 服务初始化完成")

    def destroy(self) -> None:
        if self._ready:
            self._heartbeat_thread.terminate()
            self._socket_client.destroy()
            self._socket_client = None
            self._rooms = None
            self._aircons = None
            self._new_aircons = None
            self._bathrooms = None
            self._hds = None  # 清理HD设备
            self._none_stat_dev_cnt = 0
            self._status_hook = []
            self._sensor_hook = []
            self._hd_hook = []  # 清理HD钩子
            self._heartbeat_thread = None
            self._sensors = []
            self._ready = False

    def get_aircons(self) -> list[AirCon]:
        aircons = []
        if self._new_aircons is not None:
            aircons += self._new_aircons
        if self._aircons is not None:
            aircons += self._aircons
        if self._bathrooms is not None:
            aircons += self._bathrooms
        return aircons

    def get_hds(self) -> list[HD]:
        """获取所有HD设备"""
        return self._hds if self._hds is not None else []

    def control(self, aircon: AirCon, status: AirConStatus):
        p = AirConControlParam(aircon, status)
        self.send_msg(p)

    def hd_control(self, hd: HD, status: HDStatus):
        """控制HD设备"""
        p = HDBaseControlParam(hd, status)
        #_LOGGER.debug(f"[Service] 发送HD控制命令: {hd.alias}, status={status}")
        self.send_msg(p)

    def register_status_hook(self, device: AirCon, hook: Callable):
        self._status_hook.append((device, hook))

    def register_sensor_hook(self, unique_id: str, hook: Callable):
        self._sensor_hook.append((unique_id, hook))

    def register_hd_hook(self, device: HD, hook: Callable):
        """注册HD设备状态钩子"""
        self._hd_hook.append((device, hook))
        #_LOGGER.debug(f"[Service] 注册HD钩子: {device.alias}")


    # ----split line---- above for component, below for inner call

    def is_ready(self) -> bool:
        return self._ready

    def send_msg(self, p: Param):
        """Send msg to climate gateway"""
        self._socket_client.send(p)

    def get_rooms(self):
        return self._rooms

    def set_rooms(self, v: list[Room]):
        self._rooms = v

    def get_sensors(self):
        return self._sensors

    def set_sensors(self, sensors):
        self._sensors = sensors

    def set_device(self, t: EnumDevice, v: list[AirCon]):
        self._none_stat_dev_cnt += len(v)
        if t == EnumDevice.AIRCON:
            self._aircons = v
        elif t == EnumDevice.NEWAIRCON:
            self._new_aircons = v
        else:
            self._bathrooms = v

    def set_aircon_status(
        self, target: EnumDevice, room: int, unit: int, status: AirConStatus
    ):
        if self._ready:
            self.update_aircon(target, room, unit, status=status)
        else:
            li = []
            if target == EnumDevice.AIRCON:
                li = self._aircons
            elif target == EnumDevice.NEWAIRCON:
                li = self._new_aircons
            elif target == EnumDevice.BATHROOM:
                li = self._bathrooms
            for i in li:
                if i.unit_id == unit and i.room_id == room:
                    i.status = status
                    self._none_stat_dev_cnt -= 1
                    break

    def set_sensors_status(self, sensors: list[Sensor]):
        for new_sensor in sensors:
            for sensor in self._sensors:
                if sensor.unique_id == new_sensor.unique_id:
                    for attr in STATUS_ATTR:
                        setattr(sensor, attr, getattr(new_sensor, attr))
                    break
            for item in self._sensor_hook:
                unique_id, func = item
                if new_sensor.unique_id == unique_id:
                    try:
                        func(new_sensor)
                    except Exception as e:
                        _log(str(e))

    def poll_status(self):
        """轮询设备状态"""
        _log(f"[Service.poll_status] 开始轮询所有设备状态")
        # 空调设备状态轮询
        if self._new_aircons:
            for i in self._new_aircons:
                try:
                    p = AirConQueryStatusParam()
                    p.target = EnumDevice.NEWAIRCON
                    p.device = i
                    self.send_msg(p)
                except Exception as e:
                    _LOGGER.error(f"[Service.poll_status] 空调状态查询失败: {e}")
        
        # HD设备状态轮询
        if self._hds:
            
            for hd in self._hds:
                try:
                    p = HDQueryStatusParam()
                    p.device = hd
                    self.send_msg(p)
                except Exception as e:
                    _LOGGER.error(f"[Service.poll_status] HD状态查询失败, error: {e}")
            
        # 传感器信息轮询
        try:
            p = Sensor2InfoParam()
            self.send_msg(p)
        except Exception as e:
            _LOGGER.error(f"[Service.poll_status] 传感器状态查询失败: {e}")
                

    def update_aircon(self, target: EnumDevice, room: int, unit: int, **kwargs):
        li = self._status_hook
        for item in li:
            i, func = item
            if (
                i.unit_id == unit
                and i.room_id == room
                and get_device_by_aircon(i) == target
            ):
                try:
                    func(**kwargs)
                except Exception as e:
                    _log("hook error!!")
                    _log(str(e))

    def update_hd(self, room: int, unit: int, status: HDStatus):
        """更新HD设备状态"""
        li = self._hd_hook
        try:
            if li is None:
                _log(f"[Service.update_hd] HD钩子列表为空，跳过状态更新: room={room}, unit={unit}")
                return
            
            for item in li:
                i, func = item
                if i.unit_id == unit and i.room_id == room:
                    func(status = status)
                    #_LOGGER.debug(f"[Service.update_hd] HD状态更新成功: {i.alias}")
        except Exception as e:
            _LOGGER.error(f"[Service.update_hd] HD钩子执行错误: {e}")
            _LOGGER.error(f"[Service.update_hd] 错误详情: ", exc_info=True)


    def set_hds(self, hds: list[HD]):
        """设置HD设备列表"""
        #_LOGGER.debug(f"[Service.set_hds] 接收到HD设备列表，数量: {len(hds)}")
        #for hd in hds:
            #_LOGGER.debug(f"[Service.set_hds] HD设备详情: room_id={hd.room_id}, unit_id={hd.unit_id}, alias={hd.alias}")
        self._none_stat_dev_cnt += len(hds)
        self._hds = hds
        _LOGGER.debug(f"[Service.set_hds] HD设备设置完成，当前总数: {len(self._hds)}")

    def set_hd_status(self, room: int, unit: int, status: HDStatus):
        """设置HD设备状态"""
        try:
            if self._ready:
                #_LOGGER.debug(f"[Service.set_hd_status] HD已经初始化完成，使用钩子更新状态: room={room}, unit={unit}")
                self.update_hd(room, unit, status)
            else:
                # 在初始化阶段更新HD设备状态
                #_LOGGER.debug(f"[Service.set_hd_status] HD尚未初始化，初始化HD状态: room={room}, unit={unit}")
                if(self._hds is None):
                    _LOGGER.warning(f"[Service.set_hd_status] _hds 为空")
                    return
                for hd in self._hds:
                    if hd.unit_id == unit and hd.room_id == room:
                        hd.status = status
                        self._none_stat_dev_cnt -= 1
                        #_LOGGER.debug(f"[Service.set_hd_status] 初始化阶段状态更新完成: {hd.alias}")
                        break
        except Exception as e:
            _LOGGER.error(f"[Service.set_hd_status] 设置HD状态时出错: {e}")


    def get_scan_interval(self):
        return self._scan_interval
