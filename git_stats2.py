#!/usr/bin/env python

import os
from collections import defaultdict
from datetime import date
from cPickle import dump, load
import sys
from pygit2 import Repository, GIT_SORT_TOPOLOGICAL, GIT_OBJ_COMMIT


def read_sha_set_list_txt(filename):
    try:
        with open(filename) as f:
            return set([x.strip() for x in f.readlines() if x.strip()])
    except IOError:
        return set()


def read_aliases_txt(filename):
    try:
        with open(filename) as f:
            return dict([tuple(x.strip() for x in line.split(':')) for line in f.readlines() if line.strip()])
    except IOError:
        return {}


whitelist_commits = []
blacklist_commits = []
author_aliases = {}


def defaultdict_int():
    return defaultdict(int)


def get_and_update_repo_cache(repo_path):
    cache_filename = '%s-stats.cache' % repo_path
    if os.path.exists(cache_filename):
        with open(cache_filename) as f:
            data = load(f)
    else:
        data = {
            'author_to_month_to_additions': defaultdict(defaultdict_int),
            'author_to_month_to_deletions': defaultdict(defaultdict_int),
            'author_to_month_to_commits': defaultdict(defaultdict_int),
            'day_to_count': defaultdict(defaultdict_int),
            'latest_sha': None,
        }

    repo = Repository(repo_path)

    count = 0
    for commit in repo.walk(repo.head.target, GIT_SORT_TOPOLOGICAL):
        count += 1
        if commit.type == GIT_OBJ_COMMIT:
            if data['latest_sha'] == commit.hex:
                break
        
            if not commit.message.lower().startswith('merge'):
                try:
                    d = repo.diff('%s^' % commit.hex, commit)
                except KeyError:
                    # First commit!
                    break
                patches = list(d)
                additions = sum([p.additions for p in patches])
                deletions = sum([p.deletions for p in patches])

                author = author_aliases.get(commit.author.email, commit.author.email)

                day = date.fromtimestamp(commit.commit_time)
                data['day_to_count']['Lines'][day] += additions
                data['day_to_count']['Lines'][day] -= deletions

                if additions > 1000 and deletions < 5 and commit.hex not in whitelist_commits:
                    if commit.hex not in blacklist_commits:
                        print 'WARNING: ignored %s looks like an embedding of a lib (message: %s)' % (commit.hex, commit.message)
                    continue
                if (additions > 3000 or deletions > 3000) and commit.hex not in whitelist_commits:
                    if commit.hex not in blacklist_commits and additions != deletions:  # Guess that if additions == deletions it's a big rename of files
                        print 'WARNING: ignored %s because it is bigger than 3k lines. Put this commit in the whitelist or the blacklist (message: %s)' % (commit.hex, commit.message)
                    continue
                month = date(day.year, day.month, 1)
                data['author_to_month_to_additions'][author][month] += additions
                data['author_to_month_to_deletions'][author][month] += deletions
                data['author_to_month_to_commits'][author][month] += 1
                if data['latest_sha'] is None:
                    data['latest_sha'] = commit.hex

    with open(cache_filename, 'w') as f:
        dump(data, f)

    return data


def format_series(name, data_points):
    return "{name: '%s', data: [%s]}," % (name, ', \n'.join(data_points))


def date_and_number_formatter(day, number):
    return '[Date.UTC(%s, %s, %s), %s]' % (day.year, day.month - 1, day.day, number)


def author_to_day_to_number_formatter(series_data):
    for author, date_to_number in sorted(series_data.items()):
        yield format_series(author, (date_and_number_formatter(day, number) for day, number in sorted(date_to_number.items())))


def write_series_file(formatter, series_name, series_data):
    with open('%s.js' % series_name, 'w') as output:
        output.write('var %s = [' % series_name)
        for x in formatter(series_data):
            output.write(x)
        output.write('];')


def cumulative_series(series_data):
    result = defaultdict(defaultdict_int)
    for author, date_to_number in series_data.items():
        amount = 0
        for day, number in sorted(date_to_number.items()):
            amount += number
            result[author][day] = amount
    return result


def rebase_series_to_1900(series_data):
    result = defaultdict(defaultdict_int)
    for author, date_to_number in series_data.items():
        amount = 0
        months = list(sorted(date_to_number.items()))
        date_diff = months[0][0] - date(1900, 1, 1)
        for day, number in months:
            amount += number
            result[author][day - date_diff] = amount
    return result


def main():
    if len(sys.argv) != 2:
        print 'Usage: git_stats2.py repo'
        exit(1)

    repo_name = sys.argv[1]

    whitelist_commits[:] = read_sha_set_list_txt('whitelist-%s.txt' % repo_name)
    blacklist_commits[:] = read_sha_set_list_txt('blacklist-%s.txt' % repo_name)
    author_aliases.update(read_aliases_txt('author-aliases-%s.txt' % repo_name))

    data = get_and_update_repo_cache(repo_name)
    for x in ['additions', 'deletions', 'commits']:
        d = data['author_to_month_to_%s' % x]
        write_series_file(author_to_day_to_number_formatter, x, d)
        write_series_file(author_to_day_to_number_formatter, 'rebased_1900_%s' % x, rebase_series_to_1900(d))
        write_series_file(author_to_day_to_number_formatter, 'cumulative_%s' % x, cumulative_series(d))
        write_series_file(author_to_day_to_number_formatter, 'cumulative_rebased_1900_%s' % x, rebase_series_to_1900(cumulative_series(d)))

    write_series_file(author_to_day_to_number_formatter, 'lines_per_day', cumulative_series(data['day_to_count']))

    print 'Found authors:'
    for author in sorted(data['author_to_month_to_additions'].keys()):
        print '\t', author
    print 'update author-aliases-%s.txt to fix aliasing problems' % repo_name


if __name__ == '__main__':
    main()
