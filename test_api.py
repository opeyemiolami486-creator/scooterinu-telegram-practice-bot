import tempfile
import unittest
from pathlib import Path
from aiohttp import web
from scooterinu_api import ScooterApiClient


class ScooterApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        app = web.Application()

        async def run(request):
            self.received.append(('run', request.cookies.get('device')))
            response = web.json_response({'token': 'run-token-1', 'seed': 42})
            response.set_cookie('device', 'browser-100', path='/')
            return response

        async def score(request):
            body = await request.json()
            self.received.append(('score', request.cookies.get('device'), body))
            if not body.get('name'):
                return web.json_response({'ok': False, 'reason': 'needs-name'})
            return web.json_response({'ok': True, 'name': body['name'], 'score': body['score'], 'rank': 3})

        async def board(_request):
            return web.json_response({'top': [{'name': 'Rider', 'score': 9007}]})

        app.router.add_post('/api/leaderboard/run', run)
        app.router.add_post('/api/leaderboard/score', score)
        app.router.add_get('/api/leaderboard', board)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.tmp = tempfile.TemporaryDirectory()
        self.base = f'http://127.0.0.1:{self.port}'

    async def asyncTearDown(self):
        await self.runner.cleanup()
        self.tmp.cleanup()

    async def test_run_submit_needs_name_then_claims_and_persists_device_cookie(self):
        client = ScooterApiClient(self.base, 'telegram-100', self.tmp.name)
        run = await client.begin_run()
        self.assertEqual(run, {'token': 'run-token-1', 'seed': 42})
        result = await client.submit_score(
            run['token'], [{'f': 0, 'a': 0}, {'f': 20, 'a': 1}], 9007, 'Rider_1'
        )
        self.assertEqual(result['name'], 'Rider_1')
        self.assertEqual(result['score'], 9007)
        posts = [entry for entry in self.received if entry[0] == 'score']
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0][2], {
            'token': 'run-token-1', 'events': [{'f': 0, 'a': 0}, {'f': 20, 'a': 1}], 'score': 9007
        })
        self.assertEqual(posts[1][2]['name'], 'Rider_1')
        await client.close()

        # A restart reuses the same user's cookie jar rather than creating a new device.
        client2 = ScooterApiClient(self.base, 'telegram-100', self.tmp.name)
        await client2.begin_run()
        self.assertEqual(self.received[-1], ('run', 'browser-100'))
        await client2.close()

    async def test_leaderboard_is_read_only(self):
        client = ScooterApiClient(self.base, 'telegram-200', self.tmp.name)
        board = await client.leaderboard()
        self.assertEqual(board['top'][0]['score'], 9007)
        await client.close()


if __name__ == '__main__':
    unittest.main()
