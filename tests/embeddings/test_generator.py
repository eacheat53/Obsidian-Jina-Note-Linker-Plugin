# tests/embeddings/test_generator.py

import pytest
from unittest.mock import patch, MagicMock
import requests  # 导入真实的 requests 以便模拟它的异常

# 导入您要测试的函数
from python_src.embeddings.generator import get_jina_embedding

# 使用 @patch 装饰器，这是“模拟”魔法发生的地方
# 我们要“假冒”的是 generator.py 文件里的 requests.post 函数
@patch('python_src.embeddings.generator.requests.post')
def test_get_jina_embedding_success(mock_post):
    """
    测试 get_jina_embedding 在 API 调用成功时能否正确返回 embedding。
    """
    # --- 1. 准备 (Arrange) ---
    # a. 准备函数的输入参数
    test_text = "Hello, world!"
    test_api_key = "fake_api_key"
    test_model = "jina-embeddings-v2-base-en"

    # b. 最关键的一步：设置我们“假冒”的 requests.post 的行为
    #    我们希望它返回一个“假”的响应对象。
    mock_response = MagicMock()
    #    这个假响应对象的 .json() 方法应该返回一个模拟的、成功的数据
    mock_response.json.return_value = {
        "data": [
            {
                "embedding": [0.1, 0.2, 0.3, 0.4]
            }
        ]
    }
    #    让我们的假 post 请求返回这个假响应
    mock_post.return_value = mock_response

    # --- 2. 执行 (Act) ---
    # 调用我们真正想测试的函数
    result = get_jina_embedding(
        text=test_text,
        jina_api_key_to_use=test_api_key,
        jina_model_name_to_use=test_model
    )

    # --- 3. 断言 (Assert) ---
    # a. 断言结果是不是我们期望的 embedding 列表
    assert result == [0.1, 0.2, 0.3, 0.4]

    # b. （进阶）断言我们的假 post 函数是否被正确地调用了
    mock_post.assert_called_once() # 确保它只被调用了一次
    # 可以在这里更详细地检查调用参数，但对于初学者，到此为止已经很棒了