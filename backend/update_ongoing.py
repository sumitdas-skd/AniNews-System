from database import get_db_connection
from fetcher import fetch_anime_paged, update_database

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

if __name__ == '__main__':
    update_ongoing_anime()
