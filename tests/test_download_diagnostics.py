from history_of_countries.youtube import download_failure_reason

def test_download_errors_are_classified_without_echoing_private_urls():
    error=RuntimeError("HTTP Error 403: Forbidden https://example.test/?private_token=secret")
    assert download_failure_reason(error)=="http_403"
    assert download_failure_reason(RuntimeError("Requested format is not available"))=="format_unavailable"
    assert download_failure_reason(RuntimeError("Sign in to confirm you are not a bot"))=="authentication_required"
