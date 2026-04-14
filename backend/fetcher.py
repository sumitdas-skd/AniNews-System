import os
import json
import sqlite3
import requests
import time
from database import get_db_connection

ANILIST_API_URL = 'https://graphql.anilist.co'

QUERY = '''
query ($page: Int, $perPage: Int) {
  Page (page: $page, perPage: $perPage) {
    media (type: ANIME, sort: TRENDING_DESC) {
      id
      title {
        english
        romaji
        native
      }
      status
      description
      episodes
      genres
      tags {
        name
      }
      studios(isMain: true) {
        nodes {
          name
        }
      }
      startDate {
        year
        month
        day
      }
      nextAiringEpisode {
        airingAt
        timeUntilAiring
        episode
      }
      coverImage {
        large
      }
      externalLinks {
        url
        site
        type
      }
      countryOfOrigin
      averageScore
      isAdult
    }
  }
}
'''

def fetch_anime_paged(query, variables, max_pages=5):
    all_media = []
    current_page = 1
    
    while True:
        if max_pages is not None and current_page > max_pages:
            break
            
        variables['page'] = current_page
        try:
            response = requests.post(ANILIST_API_URL, json={'query': query, 'variables': variables})
            if response.status_code == 429:
                print("Rate limited. Sleeping for 10 seconds...")
                time.sleep(10)
                continue
                
            response.raise_for_status()
            data = response.json()
            media = data['data']['Page']['media']
            if not media:
                break
            all_media.extend(media)
            current_page += 1
            time.sleep(0.5) # Gentle delay between pages
        except Exception as e:
            print(f"Error fetching page {current_page}: {e}")
            break
            
    return all_media

def fetch_anime_by_country_and_year(country_code, start_year, end_year):
    query = '''
    query ($page: Int, $perPage: Int, $country: CountryCode, $seasonYear: Int) {
      Page (page: $page, perPage: $perPage) {
        media (type: ANIME, countryOfOrigin: $country, seasonYear: $seasonYear, sort: POPULARITY_DESC) {
          id
          title {
            english
            romaji
            native
          }
          status
          description
          startDate {
            year
            month
            day
          }
          coverImage {
            large
          }
          countryOfOrigin
          isAdult
        }
      }
    }
    '''
    
    all_results = []
    for year in range(start_year, end_year + 1):
        print(f"Fetching {country_code} anime for {year}...")
        variables = {
            'perPage': 50,
            'country': country_code,
            'seasonYear': year
        }
        # Set to None to fetch ALL results available for this year/country
        results = fetch_anime_paged(query, variables, max_pages=None)
        all_results.extend(results)
        
    return all_results

def fetch_anime_by_country(country_code):
    variables = {
        'perPage': 50,
        'country': country_code
    }
    
    query_with_country = '''
    query ($page: Int, $perPage: Int, $country: CountryCode) {
      Page (page: $page, perPage: $perPage) {
        media (type: ANIME, countryOfOrigin: $country, sort: POPULARITY_DESC) {
          id
          title {
            english
            romaji
            native
          }
          status
          description
          episodes
          genres
          tags {
            name
          }
          studios(isMain: true) {
            nodes {
              name
            }
          }
          startDate {
            year
            month
            day
          }
          nextAiringEpisode {
            airingAt
            timeUntilAiring
            episode
          }
          coverImage {
            large
          }
          externalLinks {
            url
            site
            type
          }
          countryOfOrigin
          averageScore
          isAdult
        }
      }
    }
    '''
    return fetch_anime_paged(query_with_country, variables, max_pages=10)

def fetch_anime_by_year(year):
    variables = {
        'perPage': 50,
        'seasonYear': year
    }
    
    query_with_year = '''
    query ($page: Int, $perPage: Int, $seasonYear: Int) {
      Page (page: $page, perPage: $perPage) {
        media (type: ANIME, seasonYear: $seasonYear, sort: POPULARITY_DESC) {
          id
          title {
            english
            romaji
            native
          }
          status
          description
          episodes
          genres
          tags {
            name
          }
          studios(isMain: true) {
            nodes {
              name
            }
          }
          startDate {
            year
            month
            day
          }
          nextAiringEpisode {
            airingAt
            timeUntilAiring
            episode
          }
          coverImage {
            large
          }
          externalLinks {
            url
            site
            type
          }
          countryOfOrigin
          averageScore
          isAdult
        }
      }
    }
    '''
    return fetch_anime_paged(query_with_year, variables, max_pages=20)

def fetch_latest_anime():
    # Fetch more trending to populate database better
    variables = { 'perPage': 50 }
    return fetch_anime_paged(QUERY, variables, max_pages=5)

def fetch_newly_released_anime():
    # Fetch anime explicitly by their release date to catch brand new non-trending animes
    query = '''
    query ($page: Int, $perPage: Int) {
      Page (page: $page, perPage: $perPage) {
        media (type: ANIME, sort: [START_DATE_DESC, POPULARITY_DESC], status_not: NOT_YET_RELEASED) {
          id
          title { english romaji native }
          status description episodes genres
          tags { name }
          studios(isMain: true) { nodes { name } }
          startDate { year month day }
          nextAiringEpisode { airingAt timeUntilAiring episode }
          coverImage { large }
          externalLinks { url site type }
          countryOfOrigin averageScore isAdult
        }
      }
    }
    '''
    variables = { 'perPage': 50 }
    return fetch_anime_paged(query, variables, max_pages=3)
    
def fetch_upcoming_anime():
    # Fetch anime strictly in the UPCOMING state sorted by when they will release
    query = '''
    query ($page: Int, $perPage: Int) {
      Page (page: $page, perPage: $perPage) {
        media (type: ANIME, sort: START_DATE, status: NOT_YET_RELEASED) {
          id
          title { english romaji native }
          status description episodes genres
          tags { name }
          studios(isMain: true) { nodes { name } }
          startDate { year month day }
          nextAiringEpisode { airingAt timeUntilAiring episode }
          coverImage { large }
          externalLinks { url site type }
          countryOfOrigin averageScore isAdult
        }
      }
    }
    '''
    variables = { 'perPage': 50 }
    return fetch_anime_paged(query, variables, max_pages=3)

def fetch_popular_movies():
    query = '''
    query ($page: Int, $perPage: Int) {
      Page (page: $page, perPage: $perPage) {
        media (type: ANIME, format: MOVIE, sort: TRENDING_DESC) {
          id
          title {
            english
            romaji
            native
          }
          status
          description
          episodes
          genres
          tags {
            name
          }
          studios(isMain: true) {
            nodes {
              name
            }
          }
          startDate {
            year
            month
            day
          }
          coverImage {
            large
          }
          externalLinks {
            url
            site
            type
          }
          countryOfOrigin
          averageScore
          isAdult
        }
      }
    }
    '''
    variables = { 'perPage': 50 }
    return fetch_anime_paged(query, variables, max_pages=5)

def fetch_adult_anime(year=None):
    query = '''
    query ($page: Int, $perPage: Int, $seasonYear: Int) {
      Page (page: $page, perPage: $perPage) {
        media (type: ANIME, seasonYear: $seasonYear, isAdult: true, sort: TRENDING_DESC) {
          id
          title {
            english
            romaji
            native
          }
          status
          description
          episodes
          genres
          tags {
            name
          }
          studios(isMain: true) {
            nodes {
              name
            }
          }
          startDate {
            year
            month
            day
          }
          nextAiringEpisode {
            airingAt
            timeUntilAiring
            episode
          }
          coverImage {
            large
          }
          externalLinks {
            url
            site
            type
          }
          countryOfOrigin
          averageScore
          isAdult
        }
      }
    }
    '''
    variables = { 'perPage': 50 }
    if year:
        variables['seasonYear'] = year
    # For adult content, we might want to fetch more pages to get a good base
    return fetch_anime_paged(query, variables, max_pages=5)

def get_imdb_rating(title):
    # Mocking IMDb/OMDB rating fetch for now. In a real scenario, use an API key.
    # Fallback to a calculated score if title matches certain criteria.
    # For now, we'll return a semi-random but stable rating based on title for demo purposes,
    # or return None to trigger the "Rating not available" message.
    try:
        # Example API call (commented out as it needs a key):
        # r = requests.get(f"http://www.omdbapi.com/?t={title}&apikey=YOUR_KEY")
        # data = r.json()
        # return float(data['imdbRating']), int(data['imdbVotes'].replace(',', ''))
        return None, 0
    except:
        return None, 0

def map_genres(anilist_genres, anilist_tags):
    # Mapping logic for the specific user requirements
    mapping = {
        "Action": "Action & Adventure",
        "Adventure": "Action & Adventure",
        "Slice of Life": "Slice of Life",
        "Fantasy": "Fantasy",
        "Mecha": "Sci-Fi & Mecha",
        "Sci-Fi": "Sci-Fi & Mecha",
        "Romance": "Romance",
        "Supernatural": "Supernatural & Horror",
        "Horror": "Supernatural & Horror",
        "Sports": "Sports",
        "Mahou Shoujo": "Mahou Shoujo",
        "Ecchi": "Ecchi"
    }
    
    mapped = set()
    for g in anilist_genres:
        if g in mapping:
            mapped.add(mapping[g])
            
    # Tag-based mapping
    tags = [t['name'] for t in anilist_tags]
    if any(t in tags for t in ["Isekai", "Reincarnation"]):
        mapped.add("Isekai")
    if any(t in tags for t in ["Iyashikei", "Healing"]):
        mapped.add("Iyashikei")
    if any(t in tags for t in ["Harem", "Reverse Harem"]):
        mapped.add("Harem / Reverse Harem")
    
    # Dark Fantasy Detection
    if "Fantasy" in anilist_genres and any(t in tags for t in ["Dark Fantasy", "Gore", "Psychological", "Demons"]):
        mapped.add("Dark Fantasy")
        
    return list(mapped)

def update_database(custom_list=None):
    is_global_trending = custom_list is None
    anime_list = custom_list if custom_list is not None else fetch_latest_anime()
    if not anime_list:
        return 0, 0
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # If this is the main trending fetch, clear old trending ranks before assigning new ones
    if is_global_trending:
        cursor.execute("UPDATE anime SET trending_rank = NULL WHERE trending_rank IS NOT NULL")
    
    new_entries = 0
    updates = 0
    
    for index, item in enumerate(anime_list):
        # We only assign trending ranks to the main fetch_latest_anime global trending list
        new_trending_rank = index + 1 if is_global_trending else None
        
        anilist_id = item['id']
        title = item['title']['english'] or item['title']['romaji'] or item['title']['native'] or "Unknown Title"
        status_map = {
            'FINISHED': 'Completed',
            'RELEASING': 'Ongoing',
            'NOT_YET_RELEASED': 'Upcoming',
            'CANCELLED': 'Cancelled',
            'HIATUS': 'Ongoing'
        }
        status = status_map.get(item['status'], 'Upcoming')
        
        start_date = item['startDate']
        release_date = "TBA"
        if start_date.get('year'):
            year = start_date['year']
            month = f"{start_date.get('month') or 1:02d}"
            day = f"{start_date.get('day') or 1:02d}"
            release_date = f"{year}-{month}-{day}"
            
        description = item['description']
        poster_url = item['coverImage']['large']
        country = item.get('countryOfOrigin', 'JP')
        is_adult = 1 if item.get('isAdult') else 0
        
        episodes_total = item.get('episodes')
        studio = item['studios']['nodes'][0]['name'] if item.get('studios') and item['studios']['nodes'] else "Unknown"
        
        # Genre Mapping
        mapped_genres = map_genres(item.get('genres', []), item.get('tags', []))
        genres_str = ",".join(mapped_genres) 
        
        next_ep_airing = item.get('nextAiringEpisode')
        next_episode_date = None
        episodes_current = None
        last_episode_number = None
        last_episode_name = None
        
        if next_ep_airing:
            next_episode_date = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(next_ep_airing['airingAt']))
            episodes_current = next_ep_airing['episode'] - 1
            last_episode_number = episodes_current
            last_episode_name = f"Episode {episodes_current}" if episodes_current else None
            
            if episodes_current and episodes_current > 0 and status == 'Upcoming':
                status = 'Ongoing'
        
        if status == 'Completed' or (episodes_total and episodes_current and episodes_current >= episodes_total):
            status = 'Completed'
            episodes_current = episodes_total
            last_episode_number = episodes_total
            last_episode_name = f"Final Episode"
        elif not episodes_current and status == 'Ongoing':
            # Fallback if nextAirringEpisode is missing but it's "Releasing"
            episodes_current = episodes_total # Logic depends on how you want to handle this
            
        rating_score, rating_votes = get_imdb_rating(title)
        if not rating_score and item.get('averageScore'):
            rating_score = item['averageScore'] / 10.0
            
        # Check if exists
        cursor.execute("SELECT id, trending_rank FROM anime WHERE anilist_id = ?", (anilist_id,))
        existing = cursor.fetchone()
        
        # If not the global trending fetch, keep the existing trending_rank (if any)
        if not is_global_trending and existing:
            final_trending_rank = existing['trending_rank']
        else:
            final_trending_rank = new_trending_rank
        
        anime_id = None
        if existing:
            anime_id = existing['id']
            # Auto-approve existing ones if they are from trusted source (update_database is only called for trusted)
            cursor.execute('''
                UPDATE anime 
                SET status = ?, release_date = ?, country = ?, episodes_total = ?, 
                    episodes_current = ?, last_episode_number = ?, last_episode_name = ?,
                    next_episode_date = ?, studio = ?, rating_score = ?, 
                    rating_votes = ?, genres = ?, trending_rank = ?, is_adult = ?, 
                    updated_at = CURRENT_TIMESTAMP, is_approved = 1
                WHERE anilist_id = ?
            ''', (status, release_date, country, episodes_total, episodes_current, 
                  last_episode_number, last_episode_name, next_episode_date, 
                  studio, rating_score, rating_votes, genres_str, final_trending_rank, is_adult, anilist_id))
            updates += 1
        else:
            # Auto-approve ALL from trusted source
            is_approved = 1
                
            cursor.execute('''
                INSERT INTO anime (anilist_id, title, release_date, status, description, poster_url, country, 
                                 is_approved, episodes_total, episodes_current, last_episode_number, 
                                 last_episode_name, next_episode_date, studio, rating_score, rating_votes, genres, trending_rank, is_adult)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (anilist_id, title, release_date, status, description, poster_url, country, 
                  is_approved, episodes_total, episodes_current, last_episode_number, 
                  last_episode_name, next_episode_date, studio, rating_score, rating_votes, genres_str, final_trending_rank, is_adult))
            anime_id = cursor.lastrowid
            new_entries += 1
            
        # Populate episodes table (Optimized: only if not already populated or needed)
        if episodes_total:
            # Check if we already have episodes to avoid 1000+ individual checks
            cursor.execute("SELECT COUNT(*) FROM episodes WHERE anime_id = ?", (anime_id,))
            existing_count = cursor.fetchone()[0]
            if existing_count < episodes_total:
                ep_data = [
                    (anime_id, ep_num, f"Episode {ep_num}") 
                    for ep_num in range(existing_count + 1, (episodes_total or 0) + 1)
                ]
                if ep_data:
                    cursor.executemany("INSERT OR IGNORE INTO episodes (anime_id, episode_number, episode_name) VALUES (?, ?, ?)", ep_data)
                             
        # Populate relational genres
        for g_name in mapped_genres:
            cursor.execute("SELECT id FROM genres WHERE genre_name = ?", (g_name,))
            g_row = cursor.fetchone()
            if g_row:
                cursor.execute("INSERT OR IGNORE INTO anime_genres (anime_id, genre_id) VALUES (?, ?)", (anime_id, g_row['id']))

        # Populate streaming platforms
        if item.get('externalLinks'):
            for link in item['externalLinks']:
                if link['type'] == 'STREAMING':
                    cursor.execute('''
                        INSERT OR REPLACE INTO streaming_platforms (anime_id, platform_name, url)
                        VALUES (?, ?, ?)
                    ''', (anime_id, link['site'], link['url']))
            
    conn.commit()
    conn.close()
    
    return new_entries, updates

def update_ongoing_anime():
    print("Updating 'Ongoing' anime statuses...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT anilist_id FROM anime WHERE status = 'Ongoing'")
    ongoing_anime = cursor.fetchall()
    conn.close()
    
    if not ongoing_anime:
        print("No ongoing anime to update.")
        return 0, 0
        
    ids = [row['anilist_id'] for row in ongoing_anime if row['anilist_id'] is not None]
    
    total_new = 0
    total_updated = 0
    
    def chunker(seq, size):
        return (seq[pos:pos + size] for pos in range(0, len(seq), size))
        
    for chunk in chunker(ids, 50):
        query = '''
        query ($ids: [Int], $page: Int, $perPage: Int) {
          Page (page: $page, perPage: $perPage) {
            media (id_in: $ids, type: ANIME) {
              id
              title { english romaji native }
              status description episodes genres
              tags { name }
              studios(isMain: true) { nodes { name } }
              startDate { year month day }
              nextAiringEpisode { airingAt timeUntilAiring episode }
              coverImage { large }
              externalLinks { url site type }
              countryOfOrigin averageScore isAdult
            }
          }
        }
        '''
        variables = {'ids': chunk, 'perPage': 50}
        try:
            results = fetch_anime_paged(query, variables, max_pages=1)
            n, u = update_database(custom_list=results)
            total_new += n
            total_updated += u
        except Exception as e:
            print(f"Error updating chunk: {e}")
            
    print(f"Finished updating ongoing anime. New: {total_new}, Updated: {total_updated}")
    return total_new, total_updated

def update_all_anime():
    print("Updating ALL anime statuses dynamically...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT anilist_id FROM anime WHERE anilist_id IS NOT NULL")
    all_anime = cursor.fetchall()
    conn.close()
    
    if not all_anime:
        print("No anime in the database to update.")
        return 0, 0
        
    ids = [row['anilist_id'] for row in all_anime]
    
    total_new = 0
    total_updated = 0
    
    def chunker(seq, size):
        return (seq[pos:pos + size] for pos in range(0, len(seq), size))
        
    for chunk in chunker(ids, 50):
        query = '''
        query ($ids: [Int], $page: Int, $perPage: Int) {
          Page (page: $page, perPage: $perPage) {
            media (id_in: $ids, type: ANIME) {
              id
              title { english romaji native }
              status description episodes genres
              tags { name }
              studios(isMain: true) { nodes { name } }
              startDate { year month day }
              nextAiringEpisode { airingAt timeUntilAiring episode }
              coverImage { large }
              externalLinks { url site type }
              countryOfOrigin averageScore isAdult
            }
          }
        }
        '''
        variables = {'ids': chunk, 'perPage': 50}
        try:
            results = fetch_anime_paged(query, variables, max_pages=1)
            n, u = update_database(custom_list=results)
            total_new += n
            total_updated += u
        except Exception as e:
            print(f"Error updating chunk: {e}")
            
    print(f"Finished updating all anime. New: {total_new}, Updated: {total_updated}")
    return total_new, total_updated

def backfill_historical():
    print("Starting historical backfill from 1960...")
    total_new = 0
    for year in range(1960, 2027):
        print(f"Fetching anime for year {year}...")
        anime_list = fetch_anime_by_year(year)
        new, updated = update_database(anime_list)
        total_new += new
        print(f"Year {year} done: {new} new entries.")
    print(f"Backfill complete. Total new: {total_new}")

if __name__ == '__main__':
    from database import init_db
    init_db()
    # To run a full backfill, uncomment the line below or run with a flag
    # backfill_historical()
    update_database()
