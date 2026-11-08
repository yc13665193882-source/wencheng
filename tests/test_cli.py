"""Opening a chat-created document targets its project and waits for the service."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import store
from scripts import wencheng as cli


class OpenProjectTests(unittest.TestCase):
    def setUp(self):
        self.test_output = (ROOT / 'test-output').resolve()
        self.test_output.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='wencheng-cli-', dir=self.test_output)
        self.addCleanup(self.cleanup_data)
        self.data_patch = patch.object(store, 'DATA', Path(self.temp.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)

    def cleanup_data(self):
        target = Path(self.temp.name).resolve()
        if target.parent != self.test_output or not target.name.startswith('wencheng-cli-'):
            raise AssertionError('Refusing cleanup outside this test directory')
        self.temp.cleanup()

    def command(self, *args):
        out = StringIO()
        with patch.object(sys, 'argv', ['wencheng.py', *args]), redirect_stdout(out):
            cli.main()
        return json.loads(out.getvalue())

    def test_chat_document_opens_exact_project_and_returns_url(self):
        first = self.command('create', '--title', '对话生成验证', '--text', '第一段。')
        self.command('append', first['id'], '--text', '第二段。')
        self.command('create', '--title', '另一个项目')
        with patch.object(cli, 'ensure_service', return_value='http://127.0.0.1:8877') as ready, \
                patch.object(cli.webbrowser, 'open', return_value=True) as browser:
            result = self.command('open', first['id'], '--port', '8877')
        self.assertEqual(result['project_id'], first['id'])
        self.assertEqual(result['url'], f"http://127.0.0.1:8877/?project={first['id']}")
        self.assertTrue(result['browser_opened'])
        ready.assert_called_once_with(8877)
        browser.assert_called_once_with(result['url'])

    def test_missing_project_does_not_start_service_or_browser(self):
        with patch.object(cli, 'ensure_service') as ready, patch.object(cli.webbrowser, 'open') as browser:
            with self.assertRaises(FileNotFoundError):
                cli.open_project('a' * 32, 8765)
        ready.assert_not_called()
        browser.assert_not_called()

    def test_browser_failure_keeps_manual_url(self):
        project = self.command('create', '--title', '手动打开')
        for failure in (False, OSError('no desktop')):
            with self.subTest(failure=str(failure)), \
                    patch.object(cli, 'ensure_service', return_value='http://127.0.0.1:8765'), \
                    patch.object(cli.webbrowser, 'open') as browser:
                if isinstance(failure, Exception):
                    browser.side_effect = failure
                else:
                    browser.return_value = failure
                result = cli.open_project(project['id'], 8765)
                self.assertFalse(result['browser_opened'])
                self.assertTrue(result['url'].endswith('/?project=' + project['id']))

    def test_healthy_service_is_reused_without_spawning(self):
        with patch.object(cli, 'service_running', return_value=True), patch.object(cli.subprocess, 'Popen') as spawn:
            self.assertEqual(cli.ensure_service(8765), 'http://127.0.0.1:8765')
        spawn.assert_not_called()

    def test_cold_start_waits_for_health_before_opening_browser(self):
        project = self.command('create', '--title', '冷启动')
        process = Mock()
        process.poll.return_value = None
        events = []
        responses = iter([False, False, True])
        def probe(url):
            ready = next(responses)
            events.append(('health', ready))
            return ready
        def browse(url):
            events.append(('browser', url))
            return True
        with patch.object(cli, 'service_running', side_effect=probe), \
                patch.object(cli.subprocess, 'Popen', return_value=process) as spawn, \
                patch.object(cli.time, 'sleep'), patch.object(cli.webbrowser, 'open', side_effect=browse):
            result = cli.open_project(project['id'], 8765)
        self.assertEqual(events[-2], ('health', True))
        self.assertEqual(events[-1], ('browser', result['url']))
        self.assertEqual(spawn.call_args.args[0], [sys.executable, str(Path(cli.__file__).resolve()), 'start', '--port', '8765'])
        self.assertEqual(spawn.call_args.kwargs['stdin'], cli.subprocess.DEVNULL)
        self.assertNotIn('env', spawn.call_args.kwargs)  # Preserve WENCHENG_DATA from the parent.
        if cli.os.name == 'nt':
            self.assertEqual(spawn.call_args.kwargs['creationflags'], cli.subprocess.CREATE_NO_WINDOW)

    def test_failed_start_does_not_open_browser(self):
        project = self.command('create', '--title', '启动失败')
        process = Mock()
        process.poll.return_value = 1
        with patch.object(cli, 'service_running', return_value=False), \
                patch.object(cli.subprocess, 'Popen', return_value=process), patch.object(cli.webbrowser, 'open') as browser:
            with self.assertRaisesRegex(ValueError, '启动失败'):
                cli.open_project(project['id'], 8765)
        browser.assert_not_called()

    def test_permission_failure_does_not_spawn(self):
        with patch.object(cli, 'service_running', side_effect=ValueError('WinError 10013')), \
                patch.object(cli.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, '10013'):
                cli.ensure_service(8765)
        spawn.assert_not_called()

    def test_start_timeout_reports_log_and_stops_own_process(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(cli, 'service_running', return_value=False), \
                patch.object(cli.subprocess, 'Popen', return_value=process), \
                patch.object(cli.time, 'monotonic', side_effect=[0, 16]):
            with self.assertRaisesRegex(ValueError, 'server-8765.log'):
                cli.ensure_service(8765)
        process.terminate.assert_called_once()


class ServiceProbeTests(unittest.TestCase):
    def test_health_uses_direct_localhost_connection(self):
        with patch.object(cli.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = BytesIO(b'{"app":"wencheng","ok":true}')
            self.assertTrue(cli.service_running('http://127.0.0.1:8765'))
        self.assertEqual(build.call_args.args[0].proxies, {})

    def test_only_refused_connection_is_treated_as_not_running(self):
        with patch.object(cli.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = urllib.error.URLError(ConnectionRefusedError())
            self.assertFalse(cli.service_running('http://127.0.0.1:8765'))
            build.return_value.open.side_effect = urllib.error.URLError(PermissionError('10013'))
            with self.assertRaisesRegex(ValueError, '10013'):
                cli.service_running('http://127.0.0.1:8765')

    def test_other_service_is_rejected(self):
        for response in (b'{"app":"other","ok":true}', b'not json', b'[]'):
            with self.subTest(response=response), patch.object(cli.urllib.request, 'build_opener') as build:
                build.return_value.open.return_value = BytesIO(response)
                with self.assertRaises(ValueError):
                    cli.service_running('http://127.0.0.1:8765')


if __name__ == '__main__':
    unittest.main()
