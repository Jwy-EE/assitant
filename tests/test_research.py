from assistant_app.tools.research import parse_arxiv_feed


def test_parse_arxiv_feed() -> None:
    feed = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\">
      <entry>
        <id>http://arxiv.org/abs/2401.00001v1</id>
        <updated>2024-01-01T00:00:00Z</updated>
        <published>2024-01-01T00:00:00Z</published>
        <title> Test Paper </title>
        <summary> A useful summary. </summary>
        <author><name>Alice Example</name></author>
        <link title=\"pdf\" href=\"http://arxiv.org/pdf/2401.00001v1\" />
      </entry>
    </feed>
    """
    papers = parse_arxiv_feed(feed)
    assert len(papers) == 1
    assert papers[0].title == "Test Paper"
    assert papers[0].authors == ["Alice Example"]
    assert papers[0].pdf_url == "http://arxiv.org/pdf/2401.00001v1"
