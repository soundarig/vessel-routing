from pydantic import BaseModel

class PortResponse(BaseModel):
    port_id: str
    port_code: str
    port_name: str
    port_type: str | None = None
    geometry_type: str | None = None
    Portterminal: bool | None = None
    latitude: float | None = None
    longitude: float | None = None


class PortsPageResponse(BaseModel):
    items: list[PortResponse]
    total: int
    page: int
    page_size: int
    pages: int
