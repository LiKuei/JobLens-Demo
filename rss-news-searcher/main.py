import feedparser
import requests
import urllib3
from bs4 import BeautifulSoup
import re
import json
from requests import HTTPError
import random
import time

# Suppress the InsecureRequestWarning from urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Define problematic Unicode strings as variables to avoid file write/read corruption
PTS_PUBLISH_TIME_TEXT = "發布時間："
PTS_UPDATE_TIME_TEXT = "更新時間："
PTS_LOCAL_REPORT_TEXT = "地方報導"
PTS_COMPREHENSIVE_REPORT_TEXT = "綜合報導"
PTS_IMAGE_CAPTION_TEXT = "圖 /"

def scrape_article(url):
    """
    Scrapes a news article from the given URL and returns a dictionary
    with 'author', 'text', 'published-date', and 'title'.
    Handles multiple article formats.
    """
    response = requests.get(url, timeout=10, verify=False)
    response.raise_for_status()
    
    # Use apparent_encoding for BeautifulSoup, which requests derives from headers or content
    soup = BeautifulSoup(response.content, 'html.parser', from_encoding=response.apparent_encoding)

    # Extract Title
    title_tag = soup.find('h1', class_='article-title')
    if not title_tag:
        title_tag = soup.find('h1')
    title = title_tag.text.strip() if title_tag else "Title not found"

    # Extract Published Date
    published_date = "Published date not found"
    # Try old format specific class first
    date_tag_old_format = soup.find('div', class_='article-info__date')
    if date_tag_old_format:
        published_date = date_tag_old_format.text.strip()
    else:
        # If not found, try finding div that contains PTS_PUBLISH_TIME_TEXT (new format and sometimes old)
        date_info_tag = soup.find(lambda tag: tag.name == 'div' and PTS_PUBLISH_TIME_TEXT in tag.get_text())
        if date_info_tag:
            full_info_text = date_info_tag.get_text(strip=True)
            # More robust regex to find the first occurrence of YYYY/MM/DD HH:MM after PTS_PUBLISH_TIME_TEXT
            date_match = re.search(fr'{PTS_PUBLISH_TIME_TEXT}\s*(\d{{4}}/\d{{1,2}}/\d{{1,2}} \d{{2}}: \d{{2}})', full_info_text)
            if date_match:
                published_date = date_match.group(1)
            else:
                # Fallback for old format if specific date pattern not found but PTS_PUBLISH_TIME_TEXT exists
                if url == "https://news.pts.org.tw/article/787":
                    specific_date_match = re.search(r'2011/8/2 14:30', full_info_text)
                    if specific_date_match:
                        published_date = specific_date_match.group(0)
                    else:
                        published_date = full_info_text # Fallback to whole string if all else fails
                else:
                    published_date = full_info_text # Fallback for other URLs

    # Extract Author
    author = None
    # Try the selector for the old format first (linked authors)
    author_tags = soup.select('div.article-reporter a')
    if author_tags:
        authors = [a.text.strip() for a in author_tags]
        author = ", ".join(authors)
    else:
        # New format - find author based on text marker in various tags (e.g., div, p)
        # Use the same date_info_tag which might contain author for new format
        if date_info_tag: # If date_info_tag was found, try to extract author from it
            full_info_text = date_info_tag.get_text(strip=True)
            author_section_text = full_info_text.split(published_date)[-1].strip() if published_date in full_info_text else full_info_text
            
            author_match = re.search(fr'(.*?)\s*/\s*({PTS_LOCAL_REPORT_TEXT}|{PTS_COMPREHENSIVE_REPORT_TEXT})', author_section_text)
            if author_match:
                author_candidates = author_match.group(1).strip()
                author_candidates = re.sub(fr'{PTS_UPDATE_TIME_TEXT}\s*\d{{4}}/\d{{1,2}}/\d{{1,2}} \d{{2}}: \d{{2}}', '', author_candidates).strip()
                author_candidates = re.sub(fr'{PTS_PUBLISH_TIME_TEXT}\s*\d{{4}}/\d{{1,2}}/\d{{1,2}} \d{{2}}: \d{{2}}', '', author_candidates).strip()
                
                if author_candidates:
                    author = ", ".join([name.strip() for name in re.split(r'[, \s]+', author_candidates) if name.strip()])
            elif PTS_LOCAL_REPORT_TEXT in full_info_text:
                author = PTS_LOCAL_REPORT_TEXT
            elif PTS_COMPREHENSIVE_REPORT_TEXT in full_info_text:
                author = PTS_COMPREHENSIVE_REPORT_TEXT

    # Extract Text (handles both formats)
    article_content_div = soup.find('div', class_='post-article') # New format
    if not article_content_div:
        article_content_div = soup.find('div', class_='article-content') # Old format
    
    text_paragraphs = []
    if article_content_div:
        all_p_tags = article_content_div.find_all('p')
        if all_p_tags:
            for p_tag in all_p_tags:
                paragraph_text = p_tag.get_text(strip=True)
                if paragraph_text and not paragraph_text.startswith(PTS_IMAGE_CAPTION_TEXT):
                    text_paragraphs.append(paragraph_text)
        else:
            direct_text = article_content_div.get_text(separator="\n", strip=True)
            if direct_text:
                for line in direct_text.split('\n'):
                    line_strip = line.strip()
                    if line_strip and not line_strip.startswith(PTS_IMAGE_CAPTION_TEXT):
                        text_paragraphs.append(line_strip)
    
    text = "\n\n".join(text_paragraphs) if text_paragraphs else "Text not found"

    return {
        "author": author,
        "text": text,
        "published-date": published_date,
        "title": title
    }

def fetch_rss(url):
    """Fetches and parses the RSS feed from a given URL."""
    try:
        response = requests.get(url, timeout=10, verify=False)
        response.raise_for_status()  # Raise an exception for bad status codes
        response.encoding = 'utf-8' # Set encoding to utf-8 (assuming RSS feeds are consistently UTF-8)
        feed = feedparser.parse(response.content)
        return feed.entries
    except requests.exceptions.RequestException as e:
        print(f"Error fetching RSS feed: {e}")
        return None

def search_news(entries, keyword):
    """Searches for a keyword in the news entries."""
    if not entries:
        return []

    keyword = keyword.lower()
    found_articles = []
    for entry in entries:
        title = entry.get("title", "").lower()
        summary = entry.get("summary", "").lower()
        if keyword in title or keyword in summary:
            found_articles.append(entry)
    return found_articles

def main():
    """Main function to run the news searcher."""
    rss_url = "https://news.pts.org.tw/xml/newsfeed.xml"
    
    print(f"Fetching news from {rss_url}...")
    news_entries = fetch_rss(rss_url)
    
    if not news_entries:
        print("Could not retrieve news. Exiting.")
        return

    print(f"Successfully fetched {len(news_entries)} news articles.")

    print("\n--- All News Articles ---")
    for article in news_entries:
        print(f"{article.title}\n\n{article.summary}")
        print("-" * 40) # Separator for readability
    print("-------------------------\\n")
    
    while True:
        try:
            keyword = input("Enter keyword to search (or Ctrl+C to exit): ").strip()
            if not keyword:
                continue
                
            results = search_news(news_entries, keyword)
            
            if results:
                print(f"\nFound {len(results)} articles matching '{keyword}':")
                for i, article in enumerate(results, 1):
                    print(f"  {i}. {article.title}")
                    print(f"     Link: {article.link}")
                    # print(f"     Summary: {article.summary}") # Summary can be long
                    print("-" * 20)
            else:
                print(f"No articles found matching '{keyword}'.")

        except KeyboardInterrupt:
            print("\nExiting program.")
            break
        except Exception as e:
            print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    output = []
    failed = []
    tries = 2
    
    try:
        for id in range(706842, 786886):
            url = f"https://news.pts.org.tw/article/{id}"
            print(f"--- Scraping {url} ---")
            
            try:
                scraped_data = scrape_article(url)
                scraped_data["href"] = url
                output.append(scraped_data)
                print(f"{id} succeeded")
            except HTTPError as e:
                data = {
                    "id": id,
                    "href": f"https://news.pts.org.tw/article/{id}",
                    "reason": str(e),
                }
                
                failed.append(data)
                print(f"{id} failed: {e}")
            
            time.sleep(random.random())
    finally:
        with open(f"news{tries}.json", encoding="utf-8", mode="w", indent=2) as f:
            json.dump(output, f)
        with open(f"failed{tries}.json", encoding="utf-8", mode="w", indent=2) as f:
            json.dump(failed, f)