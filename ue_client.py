# ue_client.py - rewrite based on actual output

import paramiko
import os
import re
import json
import time

class UEClient:
    def __init__(self, host="140.118.162.81", user="sshuser", password=None):
        self.host = host
        self.user = user
        self.password = password or os.getenv('UE_SSH_PASSWORD')
        self.client = None

    def _connect(self):
        if self.client is None:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(self.host, username=self.user, password=self.password, timeout=10)

    def _run_adb(self, cmd, timeout=10):
        try:
            self._connect()
            stdin, stdout, stderr = self.client.exec_command(f'adb shell {cmd}', timeout=timeout)
            output = stdout.read().decode('utf-8').strip()
            returncode = stdout.channel.recv_exit_status()
            return output, returncode
        except: return None, -1

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    def is_attached(self):
        """Check if UE has data IP"""
        out, code = self._run_adb('ip addr show rmnet_data0')
        if code != 0:
            return False
        return '10.45.' in out

    def get_data_ip(self):
        """Get data interface IP"""
        out, code = self._run_adb('ip addr show rmnet_data0')
        if code != 0:
            return None
        match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', out)
        return match.group(1) if match else None

    def get_nr_state(self):
        """Get NR connection state from nrState field"""
        out, code = self._run_adb('dumpsys telephony.registry')
        if code != 0:
            return None

        # Look for PS domain nrState
        match = re.search(r'domain=PS.*?nrState=(\w+)', out, re.DOTALL)
        return match.group(1) if match else None

    def get_data_reg_state(self):
        """Get data registration state"""
        out, code = self._run_adb('dumpsys telephony.registry')
        if code != 0:
            return None

        # mDataRegState=0(IN_SERVICE) or =1(OUT_OF_SERVICE)
        match = re.search(r'mDataRegState=(\d+)\((\w+)\)', out)
        if match:
            return {
                'code': int(match.group(1)),
                'state': match.group(2)
            }
        return None

    def get_network_type(self):
        """Get radio access technology"""
        out, code = self._run_adb('dumpsys telephony.registry')
        if code != 0:
            return None

        # getRilDataRadioTechnology=20(NR_SA)
        match = re.search(r'getRilDataRadioTechnology=(\d+)\((\w+)\)', out)
        if match:
            return {
                'code': int(match.group(1)),
                'type': match.group(2)
            }
        return None

    def is_airplane_mode(self):
        """Check airplane mode"""
        out, code = self._run_adb('settings get global airplane_mode_on')
        if code != 0:
            return None
        return out == '1'

    def ping_test(self, target="10.45.0.1", count=5):
        """Ping test"""
        out, code = self._run_adb(f'ping -c {count} {target}', timeout=count+5)
        if code != 0 or not out:
            return None

        loss = re.search(r'(\d+)% packet loss', out)
        rtt = re.search(r'rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)', out)

        result = {}
        if loss:
            result['loss_percent'] = int(loss.group(1))
        if rtt:
            result['rtt_min_ms'] = float(rtt.group(1))
            result['rtt_avg_ms'] = float(rtt.group(2))
            result['rtt_max_ms'] = float(rtt.group(3))
            result['rtt_mdev_ms'] = float(rtt.group(4))

        return result

    def run_iperf(self, bitrate=10, duration=20):
        """Run iperf3 downlink test"""
        cmd = f'/data/local/tmp/iperf3 -c 10.45.0.1 -u -b {bitrate}M -t {duration} -R -i 0 -l 1300 -Z -J'
        out, code = self._run_adb(cmd, timeout=duration+10)

        if code != 0 or not out:
            return None

        try:
            return json.loads(out)
        except:
            return None

    def get_signal(self):
        """Get NR signal strength"""
        out, code = self._run_adb('dumpsys telephony.registry')
        if code != 0:
            return None

        # Find mNr signal section
        match = re.search(r'mNr=CellSignalStrengthNr:\{[^}]*ssRsrp\s*=\s*(-?\d+)[^}]*ssRsrq\s*=\s*(-?\d+)[^}]*ssSinr\s*=\s*(-?\d+)', out)
        if not match:
            return None

        return {
            'rsrp': int(match.group(1)),
            'rsrq': int(match.group(2)),
            'sinr': int(match.group(3))
        }

    def get_device_info(self):
        """Get UE device information"""
        brand, _ = self._run_adb('getprop ro.product.brand')
        model, _ = self._run_adb('getprop ro.product.model')
        manufacturer, _ = self._run_adb('getprop ro.product.manufacturer')

        return {
            'brand': brand,
            'model': model,
            'manufacturer': manufacturer
        }

    def get_android_version(self):
        """Get Android version"""
        version, _ = self._run_adb('getprop ro.build.version.release')
        sdk, _ = self._run_adb('getprop ro.build.version.sdk')

        return {
            'version': version,
            'sdk': sdk
        }

    def get_modem_baseband(self):
        """Get modem firmware version"""
        baseband, _ = self._run_adb('getprop gsm.version.baseband')
        return baseband

    # ue_client.py - add cell detection method

    def get_detected_cells(self):
        """Get all detected cellular stations (serving + neighbors)"""
        out, code = self._run_adb('dumpsys telephony.registry')
        if code != 0:
            return None

        # Find mCellInfo section
        match = re.search(r'mCellInfo=\[(.*?)\](?:\s|$)', out, re.DOTALL)
        if not match:
            return None

        cell_info_raw = match.group(1)

        # Split by CellInfoNr or CellInfoLte entries
        cell_entries = re.findall(r'CellInfo\w+:\{(.*?)\}(?=\s*(?:CellInfo|$))', cell_info_raw, re.DOTALL)

        cells = []
        for entry in cell_entries:
            cell = {}

            # Registration status
            registered = re.search(r'mRegistered=(\w+)', entry)
            cell['registered'] = registered.group(1) == 'YES' if registered else False

            # Cell identity
            pci = re.search(r'mPci\s*=\s*(\d+)', entry)
            tac = re.search(r'mTac\s*=\s*(\d+)', entry)
            arfcn = re.search(r'mNrArfcn\s*=\s*(\d+)', entry)
            earfcn = re.search(r'mEarfcn\s*=\s*(\d+)', entry)
            mcc = re.search(r'mMcc\s*=\s*(\d+)', entry)
            mnc = re.search(r'mMnc\s*=\s*(\d+)', entry)
            nci = re.search(r'mNci\s*=\s*(\d+)', entry)

            if pci:
                cell['pci'] = int(pci.group(1))
            if tac:
                cell['tac'] = int(tac.group(1))
            if arfcn:
                cell['arfcn'] = int(arfcn.group(1))
                cell['technology'] = 'NR'
            elif earfcn:
                cell['arfcn'] = int(earfcn.group(1))
                cell['technology'] = 'LTE'
            if mcc:
                cell['mcc'] = mcc.group(1)
            if mnc:
                cell['mnc'] = mnc.group(1)
            if nci:
                cell['nci'] = int(nci.group(1))

            # Signal strength
            ssRsrp = re.search(r'ssRsrp\s*=\s*(-?\d+)', entry)
            ssRsrq = re.search(r'ssRsrq\s*=\s*(-?\d+)', entry)
            ssSinr = re.search(r'ssSinr\s*=\s*(-?\d+)', entry)
            rsrp = re.search(r'(?<!ss)rsrp\s*=\s*(-?\d+)', entry)
            rsrq = re.search(r'(?<!ss)rsrq\s*=\s*(-?\d+)', entry)

            if ssRsrp:
                cell['rsrp'] = int(ssRsrp.group(1))
            elif rsrp:
                cell['rsrp'] = int(rsrp.group(1))

            if ssRsrq:
                cell['rsrq'] = int(ssRsrq.group(1))
            elif rsrq:
                cell['rsrq'] = int(rsrq.group(1))

            if ssSinr:
                cell['sinr'] = int(ssSinr.group(1))

            # Signal level
            level = re.search(r'level\s*=\s*(\d+)', entry)
            if level:
                cell['signal_level'] = int(level.group(1))

            cells.append(cell)

        # Sort: serving cell first, then by signal strength
        cells.sort(key=lambda x: (not x['registered'], -x.get('rsrp', -999)))

        return {
            'serving_cell': cells[0] if cells and cells[0]['registered'] else None,
            'neighbor_cells': [c for c in cells if not c['registered']],
            'total_detected': len(cells)
        }

    def set_airplane_mode(self, enabled):
        """Enable or disable airplane mode"""
        action = 'enable' if enabled else 'disable'
        out, code = self._run_adb(f'cmd connectivity airplane-mode {action}')
        return code == 0

    def enable_airplane_mode(self):
        """Enable airplane mode"""
        return self.set_airplane_mode(True)

    def disable_airplane_mode(self):
        """Disable airplane mode"""
        return self.set_airplane_mode(False)

    def set_mobile_data(self, enabled):
        """Enable or disable mobile data"""
        action = 'enable' if enabled else 'disable'
        out, code = self._run_adb(f'svc data {action}')
        return code == 0

    def enable_mobile_data(self):
        """Enable mobile data"""
        return self.set_mobile_data(True)

    def disable_mobile_data(self):
        """Disable mobile data"""
        return self.set_mobile_data(False)

    def get_network_type_prop(self):
        """Get network type from system property (alternative method)"""
        out, code = self._run_adb('getprop gsm.network.type')
        return out if code == 0 else None

    def get_connectivity_state(self):
        """Get connectivity state for mobile/cellular"""
        out, code = self._run_adb('dumpsys connectivity')
        if code != 0:
            return None

        # Extract mobile network state
        mobile_active = 'Mobile' in out and 'CONNECTED' in out

        return {
            'mobile_active': mobile_active,
            'raw_connectivity': out if len(out) < 500 else out[:500]  # Limit size
        }

    def get_phone_service_state(self):
        """Get detailed service state from phone subsystem"""
        out, code = self._run_adb('dumpsys phone')
        if code != 0:
            return None

        # Extract service state
        match = re.search(r'mServiceState.*?mVoiceRegState=(\d+).*?mDataRegState=(\d+)', out, re.DOTALL)
        if match:
            return {
                'voice_reg': int(match.group(1)),
                'data_reg': int(match.group(2))
            }
        return None

    def enable_radio_logging(self):
        """Enable radio logging (Qualcomm devices)"""
        out, code = self._run_adb('setprop persist.vendor.radio.adb_log_on 1')
        return code == 0

    def disable_radio_logging(self):
        """Disable radio logging"""
        out, code = self._run_adb('setprop persist.vendor.radio.adb_log_on 0')
        return code == 0

    def capture_radio_log(self, duration=10):
        """Capture radio logcat for debugging
        Returns: log content as string
        """
        try:
            self._connect()

            # Start logcat process
            cmd = ['ssh', f'{self.user}@{self.host}', 'adb logcat -b radio -v time']
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            # Capture for duration
            time.sleep(duration)
            process.terminate()

            stdout, _ = process.communicate(timeout=5)
            return stdout
        except:
            return None

    def get_radio_log_status(self):
        """Check if radio logging is enabled"""
        out, code = self._run_adb('getprop persist.vendor.radio.adb_log_on')
        return out == '1' if code == 0 else False

    def get_cell_info(self):
        """Get serving cell info with operator details"""
        out, code = self._run_adb('dumpsys telephony.registry')
        if code != 0:
            return None

        # Find CellIdentityNr section
        match = re.search(r'CellIdentityNr:\{[^}]*mPci\s*=\s*(\d+)[^}]*mTac\s*=\s*(\d+)[^}]*mNrArfcn\s*=\s*(\d+)[^}]*mMcc\s*=\s*(\d+)[^}]*mMnc\s*=\s*(\d+)[^}]*mNci\s*=\s*(\d+)[^}]*mAlphaLong\s*=\s*(\w+)[^}]*mAlphaShort\s*=\s*(\w+)', out)

        if not match:
            return None

        return {
            'pci': int(match.group(1)),
            'tac': int(match.group(2)),
            'arfcn': int(match.group(3)),
            'mcc': match.group(4),
            'mnc': match.group(5),
            'nci': int(match.group(6)),
            'operator_long': match.group(7),
            'operator_short': match.group(8)
        }

    def get_signal_level(self):
        """Get signal bar level (0-5)"""
        out, code = self._run_adb('dumpsys telephony.registry')
        if code != 0:
            return None

        # Find nrLevel in SignalBarInfo
        match = re.search(r'nrLevel=(\d+)', out)
        return int(match.group(1)) if match else None
