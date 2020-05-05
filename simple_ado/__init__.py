#!/usr/bin/env python3

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""ADO API wrapper."""

import logging
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

import requests

from simple_ado.builds import ADOBuildClient
from simple_ado.context import ADOContext
from simple_ado.exceptions import ADOException
from simple_ado.git import ADOGitClient
from simple_ado.graph import ADOGraphClient
from simple_ado.governance import ADOGovernanceClient
from simple_ado.http_client import ADOHTTPClient, ADOResponse
from simple_ado.pools import ADOPoolsClient
from simple_ado.pull_requests import ADOPullRequestClient
from simple_ado.security import ADOSecurityClient
from simple_ado.user import ADOUserClient
from simple_ado.workitems import ADOWorkItemsClient


class ADOClient:
    """Wrapper class around the ADO API.

    :param str username: The username for the user who is accessing the API
    :param str tenant: The ADO tenant to connect to
    :param str project_id: The identifier for the project
    :param str repository_id: The identifier for the repository
    :param Tuple[str,str] credentials: The credentials to use for the API connection
    :param str status_context: The context for any statuses placed on a PR or commit
    :param Optional[Dict[str,str]] extra_headers: Any extra headers which should be sent with the API requests
    :param Optional[logging.Logger] log: The logger to use for logging (a new one will be used if one is not supplied)
    """

    # pylint: disable=too-many-instance-attributes

    log: logging.Logger

    _context: ADOContext
    http_client: ADOHTTPClient

    builds: ADOBuildClient
    git: ADOGitClient
    governance: ADOGovernanceClient
    graph: ADOGraphClient
    pools: ADOPoolsClient
    security: ADOSecurityClient
    user: ADOUserClient
    workitems: ADOWorkItemsClient

    def __init__(
        self,
        *,
        username: str,
        tenant: str,
        project_id: str,
        repository_id: str,
        credentials: Tuple[str, str],
        status_context: str,
        extra_headers: Optional[Dict[str, str]] = None,
        log: Optional[logging.Logger] = None,
    ) -> None:
        """Construct a new client object."""

        if log is None:
            self.log = logging.getLogger("ado")
        else:
            self.log = log.getChild("ado")

        self._context = ADOContext(
            username=username, repository_id=repository_id, status_context=status_context
        )

        self.http_client = ADOHTTPClient(
            tenant=tenant,
            project_id=project_id,
            credentials=credentials,
            log=self.log,
            extra_headers=extra_headers,
        )

        self.builds = ADOBuildClient(self._context, self.http_client, self.log)
        self.git = ADOGitClient(self._context, self.http_client, self.log)
        self.governance = ADOGovernanceClient(self._context, self.http_client, self.log)
        self.graph = ADOGraphClient(self._context, self.http_client, self.log)
        self.pools = ADOPoolsClient(self._context, self.http_client, self.log)
        self.security = ADOSecurityClient(self._context, self.http_client, self.log)
        self.user = ADOUserClient(self._context, self.http_client, self.log)
        self.workitems = ADOWorkItemsClient(self._context, self.http_client, self.log)

    def verify_access(self) -> bool:
        """Verify that we have access to ADO.

        :returns: True if we have access, False otherwise
        """

        request_url = f"{self.http_client.base_url()}/git/repositories?api-version=1.0"

        try:
            response = self.http_client.get(request_url)
            response_data = self.http_client.decode_response(response)
            self.http_client.extract_value(response_data)
        except ADOException:
            return False

        return True

    def create_pull_request(
        self,
        source_branch: str,
        target_branch: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        reviewer_ids: Optional[List[str]] = None,
    ) -> ADOResponse:
        """Creates a pull request with the given information

        :param source_branch: The source branch of the pull request
        :param target_branch: The target branch of the pull request
        :param title: The title of the pull request
        :param description: The description of the pull request
        :param reviewer_ids: The reviewer IDs to be added to the pull request

        :returns: The ADO response with the data in it

        :raises ADOException: If we fail to create the pull request
        """
        self.log.debug("Creating pull request")

        request_url = (
            f"{self.http_client.base_url()}/git/repositories/{self._context.repository_id}"
        )
        request_url += "/pullRequests?api-version=5.1"

        body: Dict[str, Any] = {
            "sourceRefName": _canonicalize_branch_name(source_branch),
            "targetRefName": _canonicalize_branch_name(target_branch),
        }

        if title is not None:
            body["title"] = title

        if description is not None:
            body["description"] = description

        if reviewer_ids is not None and len(reviewer_ids) > 0:
            body["reviewers"] = [{"id": reviewer_id} for reviewer_id in reviewer_ids]

        response = self.http_client.post(request_url, json_data=body)
        return self.http_client.decode_response(response)

    def pull_request(self, pull_request_id: int) -> ADOPullRequestClient:
        """Get an ADOPullRequestClient for the PR identifier.

        :param pull_request_id: The ID of the pull request to create the client for

        :returns: A new ADOPullRequest client for the pull request specified
        """
        return ADOPullRequestClient(self._context, self.http_client, self.log, pull_request_id)

    def list_all_pull_requests(self, *, branch_name: Optional[str] = None) -> ADOResponse:
        """Get the pull requests for a branch from ADO.

        :param branch_name: The name of the branch to fetch the pull requests for.
        :type branch_name: Optional[str]

        :returns: The ADO Response with the pull request data
        """

        self.log.debug("Fetching PRs")

        offset = 0
        all_prs: List[Any] = []

        while True:

            request_url = f"{self.http_client.base_url()}/git/repositories/{self._context.repository_id}/pullRequests?"

            request_url += f"$top=100&$skip={offset}"

            if branch_name is not None:
                request_url += f"&sourceRefName={_canonicalize_branch_name(branch_name)}"

            request_url += "&api-version=3.0-preview"

            response = self.http_client.get(request_url)
            response_data = self.http_client.decode_response(response)

            extracted = self.http_client.extract_value(response_data)

            if len(extracted) == 0:
                break

            all_prs.extend(extracted)

            offset += 100

        return all_prs

    def custom_get(
        self,
        *,
        url_fragment: str,
        parameters: Dict[str, Any],
        is_default_collection: bool = True,
        is_project: bool = True,
        is_internal: bool = False,
    ) -> ADOResponse:
        """Perform a custom GET REST request.

        We don't always expose everything that would be preferred to the end
        user, so to make it a little easier, we expose this method which lets
        the user perform an arbitrary GET request, but where we supply the base
        information.

        We only support GET requests as anything else is too complex to be
        exposed in a generic manner. For these cases, the requests should be
        built manually.

        :param str url_fragment: The part of the URL that comes after `_apis/`
        :param Dict[str,Any] parameters: The URL parameters to append
        :param bool is_default_collection: Whether this URL should start with the path "/DefaultCollection"
        :param bool is_project: Whether this URL should scope down to include `project_id`
        :param bool is_internal: Whether this URL should use internal API endpoint "/_api"

        :returns: The raw response
        """

        encoded_parameters = urllib.parse.urlencode(parameters)
        request_url = self.http_client.base_url(
            is_default_collection=is_default_collection,
            is_project=is_project,
            is_internal=is_internal,
        )
        request_url += f"/{url_fragment}?{encoded_parameters}"

        return self.http_client.get(request_url)


def _canonicalize_branch_name(branch_name: str) -> str:
    """Cleanup the branch name before sending it via ADO request

    :param branch_name: The name of the branch to cleanup

    :returns: The cleaned up branch name to send via ADO request
    """
    if not branch_name.startswith("refs/heads/"):
        return "refs/heads/" + branch_name

    return branch_name
