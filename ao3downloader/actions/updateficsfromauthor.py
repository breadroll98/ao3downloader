import traceback

from ao3downloader import parse_text, strings, update, parse_soup
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository
from tqdm import tqdm


def action():
    fileops = FileOps()
    with Repository(fileops) as repo:

        folder = shared.update_folder(fileops)
        update_filetypes = shared.update_types(fileops)
        links_only = shared.links_only()
        if not links_only:
            download_filetypes = shared.download_types(fileops)
            images = shared.images()
            shared.ao3_login(repo, fileops)
        else:
            download_filetypes = []
            images = False

        files = shared.get_files_of_type(folder, update_filetypes)

        print(strings.UPDATE_INFO_URLS)

        works = []
        for file in tqdm(files):
            try:
                work = update.process_file(file['path'], file['filetype'], update=False)
                if work:
                    works.append({'path': file['path'], 'link': work['link']})
                    fileops.write_log({'message': strings.MESSAGE_FIC_FILE, 'path': file['path'], 'link': work['link']})
            except Exception as e:
                fileops.write_log({'message': strings.ERROR_INCOMPLETE_FIC, 'path': file['path'], 'error': str(e), 'stacktrace': traceback.format_exc()})

        # Build map of author listing URL -> set of existing work links
        authors: dict[str, set[str]] = {}
        for w in tqdm(works):
            try:
                link = w['link'].replace('http://', 'https://')
                # fetch work page to locate the author anchor
                soup = repo.get_soup(link)
                # try to find author anchor
                author_anchor = None
                # common selector for byline author link
                anchors = soup.select('.preface .byline a[rel="author"]') or soup.select('a[rel="author"]')
                if anchors:
                    author_anchor = anchors[0]
                if not author_anchor:
                    # no author link found; skip
                    fileops.write_log({'message': strings.ERROR_INCOMPLETE_FIC, 'path': w['path'], 'link': link, 'error': 'could not find author link'})
                    continue

                href = author_anchor.get('href')
                if not href:
                    fileops.write_log({'message': strings.ERROR_INCOMPLETE_FIC, 'path': w['path'], 'link': link, 'error': 'empty author href'})
                    continue

                # normalize full author base url
                if href.startswith('http'):
                    base = href
                else:
                    base = strings.AO3_BASE_URL + href

                # ensure we point at the author's works listing
                if '/works' not in base:
                    author_listing = base.rstrip('/') + '/works'
                else:
                    author_listing = base

                if author_listing not in authors:
                    authors[author_listing] = set()
                authors[author_listing].add(link)

            except Exception as e:
                fileops.write_log({'message': strings.ERROR_INCOMPLETE_FIC, 'path': w['path'], 'link': w.get('link'), 'error': str(e), 'stacktrace': traceback.format_exc()})

        if not authors:
            print('no authors discovered from files')
            return

        if links_only:
            # gather missing links per author and write out
            all_missing = []
            for author_url, existing in authors.items():
                total_pages = None
                link_cursor = author_url
                while True:
                    page_soup = repo.get_soup(link_cursor)
                    page_soup = Ao3(repo, fileops, [], None, False, False).proceed(page_soup)
                    if total_pages is None:
                        total_pages = parse_soup.get_total_pages(page_soup)
                    work_urls = parse_soup.get_work_urls(page_soup)
                    for u in work_urls:
                        u = u.replace('http://', 'https://')
                        if u not in existing:
                            all_missing.append(u)
                    pagenum = parse_text.get_page_number(link_cursor)
                    if not total_pages or pagenum >= total_pages:
                        break
                    link_cursor = parse_text.get_next_page(link_cursor)

            if all_missing:
                path = shared.write_links_file(list(dict.fromkeys(all_missing)), 'update_author_links')
                print(strings.INFO_LINKS_FILE_WRITTEN.format(len(all_missing), path))
            else:
                print(strings.INFO_NO_LINKS_TO_WRITE)
            return

        print(strings.UPDATE_INFO_DOWNLOADING)

        ao3 = Ao3(repo, fileops, download_filetypes, None, False, images)
        visited = shared.visited(fileops, download_filetypes)

        for author_url, existing in tqdm(authors.items()):
            ao3.download_missing_fics_from_author(author_url, existing, visited)

