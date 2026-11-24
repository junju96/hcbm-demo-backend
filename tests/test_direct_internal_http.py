import unittest
from unittest.mock import MagicMock, patch

from app.services import data_server_client, vehicle_control_client


DIRECT_PROXIES = {"http": None, "https": None, "all": None}


class DirectInternalHttpTest(unittest.TestCase):
    def test_data_server_post_bypasses_all_environment_proxies(self):
        response = MagicMock()
        response.json.return_value = []
        with patch.object(data_server_client.requests, "post", return_value=response) as post:
            data_server_client._http_post("/api/v1/task_pool/resources/query", {}, silent=True)
        self.assertEqual(post.call_args.kwargs["proxies"], DIRECT_PROXIES)

    def test_resource_pool_get_bypasses_all_environment_proxies(self):
        response = MagicMock()
        response.json.return_value = []
        with patch.object(data_server_client.requests, "get", return_value=response) as get:
            data_server_client._http_get_resource_pool("/api/v1/resource_pool/resources", silent=True)
        self.assertEqual(get.call_args.kwargs["proxies"], DIRECT_PROXIES)

    def test_vehicle_info_get_bypasses_all_environment_proxies(self):
        response = MagicMock()
        response.json.return_value = []
        with patch.object(vehicle_control_client.requests, "get", return_value=response) as get:
            vehicle_control_client.query_vehicle_info_all()
        self.assertEqual(get.call_args.kwargs["proxies"], DIRECT_PROXIES)


if __name__ == "__main__":
    unittest.main()
