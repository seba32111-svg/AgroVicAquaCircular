from pymongo.errors import ConfigurationError, OperationFailure, ServerSelectionTimeoutError

from database.doctor import EXPECTED_COLLECTIONS, explain_error, find_uri_problem, inspect_database, mask_uri


def test_mask_uri_hides_password():
    uri = "mongodb+srv://usuario:secreta@cluster.abc.mongodb.net/?appName=X"
    assert mask_uri(uri) == "mongodb+srv://usuario:****@cluster.abc.mongodb.net/?appName=X"


def test_mask_uri_keeps_uri_without_credentials():
    assert mask_uri("mongodb://localhost:27017") == "mongodb://localhost:27017"


def test_find_uri_problem_detects_atlas_placeholder():
    problem = find_uri_problem("mongodb+srv://u:<db_password>@cluster.abc.mongodb.net/")
    assert problem and "<db_password>" in problem


def test_find_uri_problem_rejects_unknown_scheme():
    assert find_uri_problem("http://localhost:27017")


def test_find_uri_problem_accepts_valid_uri():
    assert find_uri_problem("mongodb://localhost:27017") is None


def test_explain_error_classifies_failures():
    assert "autenticación" in explain_error(OperationFailure("bad auth", code=18))
    assert "Network Access" in explain_error(ServerSelectionTimeoutError("timeout"))
    assert "DNS" in explain_error(ConfigurationError("The DNS query name does not exist"))


def test_inspect_database_reports_missing_and_timeseries(database):
    database.drop_collection("alertas")
    report = inspect_database(database)
    assert report["missing"] == ["alertas"]
    assert report["timeseries_ok"] is True
    assert report["counts"]["lecturas_sensor"] == 500
    assert set(report["counts"]) == set(EXPECTED_COLLECTIONS) - {"alertas"}
