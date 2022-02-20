#
# The main search hooks for the Search Flask application.
#
from flask import (
    Blueprint, redirect, render_template, request, url_for
)

from week1.opensearch import get_opensearch

bp = Blueprint('search', __name__, url_prefix='/search')


# Process the filters requested by the user and return a tuple that is appropriate for use in: the query, URLs displaying the filter and the display of the applied filters
# filters -- convert the URL GET structure into an OpenSearch filter query
# display_filters -- return an array of filters that are applied that is appropriate for display
# applied_filters -- return a String that is appropriate for inclusion in a URL as part of a query string.  This is basically the same as the input query string
def process_filters(filters_input):
    # Filters look like: &filter.name=regularPrice&regularPrice.key={{ agg.key }}&regularPrice.from={{ agg.from }}&regularPrice.to={{ agg.to }}
    filters = []
    display_filters = []  # Also create the text we will use to display the filters that are applied
    applied_filters = ""
    for filter in filters_input:
        type = request.args.get(filter + ".type")
        display_name = request.args.get(filter + ".displayName", filter)
        key = request.args.get(filter + ".key")
        # We need to capture and return what filters are already applied so they can be automatically added to any existing links we display in aggregations.jinja2
        # filters get used in create_query below.  display_filters gets used by display_filters.jinja2 and applied_filters gets used by aggregations.jinja2 (and any other links that would execute a search.)
        if type == "range":
            from_value = request.args.get(filter + ".from")
            to_value = request.args.get(filter + ".to")
            if not to_value :
                filters.append({
                    "range": {
                        filter: {
                            "gte": from_value
                        }
                    }
                })
                display_filters.append(f"{filter} from {from_value}")
            elif not from_value :
                filters.append({
                    "range": {
                        filter: {
                            "lt": to_value,
                        }
                    }
                })
                display_filters.append(f"{filter} to {to_value}")
            else:
                filters.append({
                    "range": {
                        filter: {
                            "lt": to_value,
                            "gte": from_value
                        }
                    }
                })
                display_filters.append(f"{filter} from {from_value} to {to_value}")
            applied_filters += "&filter.name={}&{}.type={}&{}.from={}&{}.to={}&{}.key={}&{}.displayName={}".format(filter, filter, type, filter, from_value, filter, to_value, filter, key, filter, display_name)
        elif type == "terms":
            filters.append({
                "term": {
                    filter: key
                }
            })
            display_filters.append(f"Only from {key} {filter}")
            applied_filters += "&filter.name={}&{}.type={}&{}.key={}&{}.displayName={}".format(filter, filter, type, filter, key, filter, display_name)
        print("Filters: {}".format(filters))

    return filters, display_filters, applied_filters


# Our main query route.  Accepts POST (via the Search box) and GETs via the clicks on aggregations/facets
@bp.route('/query', methods=['GET', 'POST'])
def query():
    opensearch = get_opensearch() # Load up our OpenSearch client from the opensearch.py file.
    # Put in your code to query opensearch.  Set error as appropriate.
    error = None
    user_query = None
    query_obj = None
    display_filters = None
    applied_filters = ""
    filters = None
    sort = "_score"
    sortDir = "desc"
    if request.method == 'POST':  # a query has been submitted
        user_query = request.form['query']
        if not user_query:
            user_query = "*"
        sort = request.form["sort"]
        if not sort:
            sort = "_score"
        sortDir = request.form["sortDir"]
        if not sortDir:
            sortDir = "desc"
        query_obj = create_query(user_query, [], sort, sortDir)
    elif request.method == 'GET':  # Handle the case where there is no query or just loading the page
        user_query = request.args.get("query", "*")
        filters_input = request.args.getlist("filter.name")
        sort = request.args.get("sort", sort)
        sortDir = request.args.get("sortDir", sortDir)
        if filters_input:
            (filters, display_filters, applied_filters) = process_filters(filters_input)

        query_obj = create_query(user_query, filters, sort, sortDir)
    else:
        query_obj = create_query("*", [], sort, sortDir)

    print("query obj: {}".format(query_obj))
    response = opensearch.search(body = query_obj, index = 'bbuy_products')   
    # Postprocess results here if you so desire

    #print(response)
    if error is None:
        return render_template("search_results.jinja2", query=user_query, search_response=response,
                               display_filters=display_filters, applied_filters=applied_filters,
                               sort=sort, sortDir=sortDir)
    else:
        redirect(url_for("index"))


def create_query(user_query, filters, sort="_score", sortDir="desc"):
    print("Query: {}\nFilters: {}\nSort: {}".format(user_query, filters, sort))
    if user_query == '*':
        query = {
        "match_all": {}
        }
    else:
        query = {
            "function_score": {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "query_string": {
                                    "fields": [
                                        "name^200",
                                        "name.stemmed^100",
                                        "shortDescription^100",
                                        "shortDescription.stemmed^50",
                                        "longDescription^20",
                                        "longDescription.stemmed^10",
                                        "department"],
                                    "query": user_query
                                }
                            }
                        ],
                        "should": [
                            {
                                "match_phrase": {
                                    "name": {
                                        "query" : user_query,
                                        "slop": 1,
                                        "boost": 100
                                    }
                                }
                            }
                        ],
                        "filter": filters
                    }
                },
                "boost_mode": "multiply",
                "score_mode": "avg",
                "functions": [
                    {
                        "field_value_factor": {
                            "field": "salesRankLongTerm",
                            "missing": 100000000,
                            "modifier": "reciprocal"
                        }
                    },
                    {
                        "field_value_factor": {
                            "field": "salesRankMediumTerm",
                            "missing": 100000000,
                            "modifier": "reciprocal"
                        }
                    },
                    {
                        "field_value_factor": {
                            "field": "salesRankShortTerm",
                            "missing": 100000000,
                            "modifier": "reciprocal"
                        }
                    },
                ]
            }
        }
    query_obj = {
        'size': 10,
        "track_total_hits": True,
        "sort": {sort: sortDir},
        "query": query,
        "aggs": {
            "missing_images": {
                "missing": { 
                    "field": "image" 
                    }
                },
            "department": {
                "terms": {
                    "field": "department"
                    }
                },
            "regularPrice": {
                    "range": {
                        "field": "regularPrice",
                        "ranges": [
                            {
                                "key": "$",
                                "to": 100
                            },
                            {
                                "key": "$$",
                                "from": 100,
                                "to": 200
                            },
                            {
                                "key": "$$$",
                                "from": 200,
                                "to": 300
                            },
                            {
                                "key": "$$$$",
                                "from": 300,
                                "to": 400                   
                            },
                            {
                                "key": "$$$$$",
                                "from": 400,
                                "to": 500                     
                            },
                            {
                                "key": "$$$$$$",
                                "from": 500                    
                            }
                        ]
                    }
                }
        }
    }
    return query_obj
