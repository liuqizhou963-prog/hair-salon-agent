import pytest

from backend.rag.retriever import retrieve


@pytest.mark.parametrize(
    ("question", "expected_title"),
    [
        ("7度底色想做冷棕怎么配？", "七度底色做冷棕的判断思路"),
        ("染膏和双氧怎么配比？", "染膏和氧化乳配比记录方法"),
        ("发根染和发尾染有什么区别？", "为什么发根反应通常更快"),
        ("漂到橙黄色应该怎么校色？", "橙黄色底色如何校色"),
        ("染发需要加热多久？", "加热条件与禁止加热情况"),
        ("受损发能不能染？", "受损发的染发处理"),
        ("染发前要做过敏测试吗？", "染发前过敏测试"),
    ],
)
def test_apprentice_hair_color_questions_retrieve_expected_knowledge(
    question, expected_title
):
    results = retrieve(question, k=3)

    assert results
    assert results[0]["title"] == expected_title
    assert results[0]["score"] > 0
