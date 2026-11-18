"""Projects in the admin's dropdowns (engine.admin_projects).

Two projects often share column and entity names. A select or autocomplete
list names each item's project; on an existing object's page it offers only
that object's project's items, on an add page all of them, labelled.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _project(name: str):
    """A project with a CUSTOMER table, its C_NAME column and a hub column."""
    from engine.models import (
        Hub,
        HubColumn,
        Project,
        SourceColumn,
        SourceSystem,
        SourceTable,
    )
    from engine.services.staging_service import get_or_create_staging_column

    project = Project.objects.create(name=name)
    system = SourceSystem.objects.create(project=project, schema_name="raw", name="CRM")
    table = SourceTable.objects.create(
        project=project, source_system=system, physical_table_name="Customer"
    )
    staging = get_or_create_staging_column(
        SourceColumn.objects.create(
            source_table=table,
            source_column_physical_name="C_NAME",
            source_column_datatype="VARCHAR",
        )
    )
    hub = Hub.objects.create(
        project=project, hub_physical_name="CUSTOMER_H", hub_hashkey_name="hk_c"
    )
    column = HubColumn.objects.create(
        hub=hub, column_name="C_NAME", column_type="business_key", sort_order=1
    )
    return project, staging, column


@pytest.fixture
def two_projects(django_setup):
    return _project("shop"), _project("shop_copy")


def _autocomplete(client, term: str, referer: str) -> list[str]:
    response = client.get(
        "/admin/autocomplete/",
        {
            "app_label": "engine",
            "model_name": "hubsourcemapping",
            "field_name": "staging_column",
            "term": term,
        },
        HTTP_REFERER=f"http://testserver{referer}",
    )
    assert response.status_code == 200
    return [result["text"] for result in response.json()["results"]]


def test_models_find_their_project(django_setup):
    from engine.admin_projects import project_path
    from engine.models import (
        HubSourceMapping,
        Project,
        SourceColumn,
        StagingColumn,
    )

    assert project_path(StagingColumn) == "project"
    assert project_path(SourceColumn) == "source_table__project"
    assert project_path(HubSourceMapping) == "hub_column__hub__project"
    assert project_path(Project) is None


def test_an_objects_page_offers_its_projects_columns(two_projects, admin_client):
    (_shop, _staging, column), _copy = two_projects

    texts = _autocomplete(
        admin_client, "C_NAME", f"/admin/engine/hubcolumn/{column.pk}/change/"
    )

    assert texts == ["[source] Customer.C_NAME · shop"]


def test_an_add_page_offers_every_projects_columns_labelled(two_projects, admin_client):
    texts = _autocomplete(admin_client, "C_NAME", "/admin/engine/hubcolumn/add/")

    assert texts == [
        "[source] Customer.C_NAME · shop",
        "[source] Customer.C_NAME · shop_copy",
    ]


def test_a_selected_column_shows_its_project(two_projects, admin_client):
    from engine.models import HubSourceMapping

    (_shop, staging, column), _copy = two_projects
    HubSourceMapping.objects.create(hub_column=column, staging_column=staging)

    page = admin_client.get(f"/admin/engine/hubcolumn/{column.pk}/change/")

    assert page.status_code == 200
    assert "[source] Customer.C_NAME · shop</option>" in page.content.decode()
