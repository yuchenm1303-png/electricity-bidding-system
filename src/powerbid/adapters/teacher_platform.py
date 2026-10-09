from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency guard
    requests = None


class TeacherPlatformError(RuntimeError):
    """Raised when the teaching PMSS platform rejects or cannot serve a request."""


@dataclass(frozen=True)
class TeacherPlatformContext:
    project: dict[str, Any]
    cases: tuple[dict[str, Any], ...]
    market_system: dict[str, Any]
    units: tuple[dict[str, Any], ...]

    @property
    def day_ahead(self) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.market_system.get("spotList", [])
                if item.get("marketAtomType") == "DA"
            ),
            None,
        )

    @property
    def real_time(self) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.market_system.get("spotList", [])
                if item.get("marketAtomType") == "RT"
            ),
            None,
        )

    def scope_id(self, *, case: dict[str, Any], market_type_atom: str) -> str:
        scene_date_key = case.get("tmSceneDateKey")
        for day in self.market_system.get("scopes", []):
            if day.get("tmSceneDateKey") != scene_date_key:
                continue
            for scope in day.get("datas", []):
                if scope.get("selfSort") == market_type_atom:
                    return str(scope["scopeId"])
        raise TeacherPlatformError(
            f"No {market_type_atom} scope found for case {case.get('caseId')}"
        )


class TeacherPlatformAdapter:
    """
    HTTP adapter for the teacher's PMSS market simulator.

    Safe by default:
    - reads execute immediately;
    - bid writes and clearing are dry-runs unless commit=True;
    - authentication is injected at runtime and is never stored in source code.
    """

    def __init__(
        self,
        *,
        base_url: str,
        proxy_url: str | None = None,
        cookies: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        if requests is None:
            raise RuntimeError(
                "TeacherPlatformAdapter requires the optional platform dependency: "
                "pip install -e '.[platform]'"
            )

        self.api_base = base_url.rstrip("/") + "/pmss/web"
        self.timeout = timeout
        self.session = requests.Session()
        if proxy_url:
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})
        if cookies:
            self.session.cookies.update(cookies)
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Connection": "close",
                "User-Agent": "PowerBid-TeacherPlatformAdapter/0.1",
            }
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = self.api_base + "/" + path.lstrip("/")
        response = None
        last_error: Exception | None = None

        # Retry only verified read endpoints. POST bid saves and POST clearing
        # may succeed remotely just before a network failure: replaying them
        # could cause duplicate submission or an extra clearing execution.
        readonly_posts = {
            "tmScene/spot/unit/getUnitDictTreeFilterByTypesWithMva",
            "scene/loadFc/list",
            "scene/unitParam/list",
            "marketResult/unitBid/listForGd",
            "marketResult/nodalLmp/list",
            "marketResult/branchFlow/list",
        }
        retryable = method.upper() == "GET" or (
            method.upper() == "POST" and path.lstrip("/") in readonly_posts
        )
        max_attempts = 3 if retryable else 1
        for attempt in range(max_attempts):
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt == max_attempts - 1:
                    raise TeacherPlatformError(
                        f"Network request failed after {max_attempts} attempt(s): "
                        f"{method} {path}: {exc}"
                    ) from exc

        if response is None:
            raise TeacherPlatformError(
                f"Network request failed: {method} {path}: {last_error}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise TeacherPlatformError(
                f"PMSS returned non-JSON data for {path}: {response.text[:300]}"
            ) from exc

        if payload.get("retCode") != "T200":
            raise TeacherPlatformError(
                f"{path} failed: retCode={payload.get('retCode')!r}, "
                f"retMsg={payload.get('retMsg')!r}"
            )
        return payload.get("data")

    def list_projects(
        self,
        *,
        page_no: int = 1,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            "project/list",
            params={
                "permissionType": 0,
                "projectType": 1,
                "pageSize": page_size,
                "pageNo": page_no,
                "version": "base",
            },
        )
        return (data or {}).get("datas", [])

    def list_cases(self, project_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "project/listSimulateCaseByProjectId",
            params={"projectId": project_id},
        ) or []

    def get_market_system(self, tm_scene_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "tmScene/getMarketSystemAndScopIds",
            params={"tmSceneId": tm_scene_id},
        ) or {}

    def get_power_model(self, net_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "powerModel/getPowerModel",
            params={"netId": net_id},
        ) or {}

    def get_unit_tree(
        self,
        *,
        project_id: str,
        net_id: str,
        join_spot_kind_field: str = "isEnergy",
    ) -> list[dict[str, Any]]:
        return self._request(
            "POST",
            "tmScene/spot/unit/getUnitDictTreeFilterByTypesWithMva",
            json_body={
                "projectId": project_id,
                "joinSpotKindField": join_spot_kind_field,
                "netId": net_id,
            },
        ) or []

    @staticmethod
    def flatten_units(tree: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        queue = list(tree)
        units: list[dict[str, Any]] = []
        while queue:
            item = queue.pop(0)
            children = item.get("children") or []
            if item.get("leaf"):
                units.append(item)
            else:
                queue[0:0] = children
        return units

    def get_context(self, project_id: str | None = None) -> TeacherPlatformContext:
        projects = self.list_projects()
        if not projects:
            raise TeacherPlatformError("No accessible PMSS project was found.")

        project = projects[0]
        if project_id is not None:
            project = next(
                (item for item in projects if item.get("projectId") == project_id),
                None,
            )
            if project is None:
                raise TeacherPlatformError(f"Project not found: {project_id}")

        cases = self.list_cases(str(project["projectId"]))
        market_system = self.get_market_system(str(project["tmSceneId"]))
        unit_tree = self.get_unit_tree(
            project_id=str(project["projectId"]),
            net_id=str(project["netId"]),
        )
        return TeacherPlatformContext(
            project=project,
            cases=tuple(cases),
            market_system=market_system,
            units=tuple(self.flatten_units(unit_tree)),
        )

    def get_da_nodal_loads(
        self, *, pm_scene_id: str, pm_scene_date_key: str,
        page_no: int = 1, page_size: int = 999,
    ) -> dict[str, Any]:
        """Read PMSS operating-scene DA node loads (query-only POST)."""
        return self._request(
            "POST",
            "scene/loadFc/list",
            json_body={
                "ids": [],
                "pageNo": page_no,
                "pageSize": page_size,
                "sceneDateKey": pm_scene_date_key,
                "sceneId": pm_scene_id,
            },
        ) or {}

    def get_scene_unit_constraints(
        self, *, scene_id: str, page_no: int = 1, page_size: int = 999,
    ) -> dict[str, Any]:
        """Read calculation-rule switches; source JS: scene/unitParam/list.

        Query-only POST; never call scene/unitParam/updateCalculateParam.
        """
        return self._request(
            "POST",
            "scene/unitParam/list",
            json_body={
                "sceneId": scene_id,
                "pageNo": page_no,
                "pageSize": page_size,
            },
        ) or {}

    def get_unit_initial_state_inputs(
        self, *, scene_id: str, project_id: str, case_id: str,
        page_no: int = 1, page_size: int = 999,
    ) -> dict[str, Any]:
        """Read initial state entries; source JS: project/getUnitInitialStateInput.

        This query neither sets nor assumes initial unit commitment.
        """
        return self._request(
            "GET",
            "project/getUnitInitialStateInput",
            params={
                "sceneId": scene_id,
                "projectId": project_id,
                "caseId": case_id,
                "pageNo": page_no,
                "pageSize": page_size,
            },
        ) or {}

    def get_unit_bid(self, *, scope_id: str, unit_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "tmScene/spot/unit/electricEnergy",
            params={"scopeId": scope_id, "unitId": unit_id},
        ) or {}

    @staticmethod
    def build_unit_bid_payload(
        *,
        scope_id: str,
        unit_id: str,
        segments: list[dict[str, float]],
        period_num: int = 24,
        min_tech_power_cost: float = 0.0,
        start_cost_hot: float = 0.0,
        start_cost_warm: float = 0.0,
        start_cost_cold: float = 0.0,
    ) -> dict[str, Any]:
        segment_data = [
            {
                "startPower": float(segment["startPower"]),
                "endPower": float(segment["endPower"]),
                "price": float(segment["price"]),
                "segmentOrder": order,
            }
            for order, segment in enumerate(segments, start=1)
        ]
        return {
            "scopeId": scope_id,
            "minTechPowerCost": float(min_tech_power_cost),
            "startCostHot": float(start_cost_hot),
            "startCostWarm": float(start_cost_warm),
            "startCostCold": float(start_cost_cold),
            "unitId": unit_id,
            "datas": [
                {
                    "startPeriod": 1,
                    "endPeriod": int(period_num),
                    "segmentDatas": segment_data,
                }
            ],
        }

    @staticmethod
    def validate_segments(
        segments: list[dict[str, float]],
        *,
        max_segments: int,
        price_min: float,
        price_max: float,
        max_power: float | None = None,
    ) -> None:
        if not segments:
            raise ValueError("At least one bidding segment is required.")
        if len(segments) > max_segments:
            raise ValueError(f"Too many segments: {len(segments)} > {max_segments}")

        previous_end: float | None = None
        for order, segment in enumerate(segments, start=1):
            start = float(segment["startPower"])
            end = float(segment["endPower"])
            price = float(segment["price"])
            if end <= start:
                raise ValueError(
                    f"Segment {order}: endPower must be greater than startPower."
                )
            if previous_end is not None and abs(start - previous_end) > 1e-9:
                raise ValueError(
                    f"Segment {order}: startPower must equal the previous endPower."
                )
            if not (price_min <= price <= price_max):
                raise ValueError(
                    f"Segment {order}: price {price} outside [{price_min}, {price_max}]."
                )
            if max_power is not None and end > max_power + 1e-9:
                raise ValueError(
                    f"Segment {order}: endPower {end} exceeds max power {max_power}."
                )
            previous_end = end

    def save_unit_bid(
        self,
        payload: dict[str, Any],
        *,
        commit: bool = False,
    ) -> dict[str, Any]:
        if not commit:
            return {
                "dry_run": True,
                "endpoint": "tmScene/spot/unit/electricEnergy",
                "payload": payload,
            }
        return self._request(
            "POST",
            "tmScene/spot/unit/electricEnergy",
            json_body=payload,
        ) or {}

    @staticmethod
    def build_clearing_payload(*, case_id: str, comment: str = "") -> dict[str, str]:
        return {"caseId": case_id, "comment": comment}

    def run_clearing(
        self,
        *,
        case_id: str,
        comment: str = "",
        commit: bool = False,
    ) -> dict[str, Any]:
        payload = self.build_clearing_payload(case_id=case_id, comment=comment)
        if not commit:
            return {
                "dry_run": True,
                "endpoint": "simulate/execute",
                "payload": payload,
            }
        return self._request("POST", "simulate/execute", json_body=payload) or {}

    def get_clearing_result(
        self,
        *,
        case_id: str,
        market_type_atom: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "simulate/getClearingResult",
            params={"caseId": case_id, "marketTypeAtom": market_type_atom},
        ) or {}

    def get_result_overview(
        self,
        *,
        case_id: str,
        market_type_atom: str = "DA",
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "marketResult/resultOverView/getResultOverViewForGd",
            params={"caseId": case_id, "marketTypeAtom": market_type_atom},
        ) or {}

    def get_unit_result_tree(self, case_id: str) -> list[dict[str, Any]]:
        """Read-only selector for unit results; use DA and RT IDs separately."""
        return self._request(
            "GET",
            "marketResult/unitBid/getSelectTree",
            params={"caseId": case_id},
        ) or []

    def get_unit_results(
        self,
        *,
        case_id: str,
        da_ids: list[str],
        rt_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "marketResult/unitBid/listForGd",
            json_body={
                "caseId": case_id,
                "daIds": da_ids,
                "rtIds": [] if rt_ids is None else rt_ids,
            },
        ) or {}

    def get_nodal_tree(self, case_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "marketResult/nodalLmp/getSelectTree",
            params={"caseId": case_id},
        ) or []

    def get_nodal_prices(
        self,
        *,
        case_id: str,
        da_ids: list[str],
        rt_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "marketResult/nodalLmp/list",
            json_body={
                "caseId": case_id,
                "daIds": da_ids,
                "rtIds": [] if rt_ids is None else rt_ids,
            },
        ) or {}

    def get_branch_tree(self, case_id: str) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "marketResult/branchFlow/getSelectTree",
            params={"caseId": case_id},
        ) or []

    def get_branch_flows(
        self,
        *,
        case_id: str,
        da_ids: list[str],
        rt_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "marketResult/branchFlow/list",
            json_body={
                "caseId": case_id,
                "daIds": da_ids,
                "rtIds": [] if rt_ids is None else rt_ids,
            },
        ) or {}
