import heapq

def heuristic(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Manhattan distance heuristic."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def a_star(
    warehouse,
    start: tuple[int, int],
    goal: tuple[int, int],
    occupied_cells: set[tuple[int, int]] | None = None,
    *,
    ignore_barriers: bool = False,
) -> list[tuple[int, int]] | None:
    """
    Standard A* pathfinding on 2D grid.
    
    Args:
        warehouse: Warehouse instance (provides is_walkable, get_neighbors)
        start: (x, y) start position
        goal: (x, y) goal position
        ignore_barriers: Diagnostic search of the building layout only. Never use
            this route for movement.
        occupied_cells: Optional set of (x,y) cells to treat as temporarily blocked
    
    Returns:
        List of (x, y) waypoints from start to goal (inclusive), or None if no path.
    """
    if start == goal:
        return [start]
    
    if occupied_cells is None:
        occupied_cells = set()
    
    open_set = []  # (f_score, counter, node)
    heapq.heappush(open_set, (0, 0, start))
    came_from = {}
    g_score = {start: 0}
    counter = 1
    
    while open_set:
        _, _, current = heapq.heappop(open_set)
        
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path
        
        if ignore_barriers:
            x, y = current
            neighbors = [cell for cell in ((x+1, y), (x-1, y), (x, y+1), (x, y-1))
                         if warehouse._structurally_walkable(*cell)]
        else:
            neighbors = warehouse.get_neighbors(*current)
        for neighbor in neighbors:
            if neighbor in occupied_cells and neighbor != goal:
                continue
            
            tentative_g = g_score[current] + 1
            
            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f_score = tentative_g + heuristic(neighbor, goal)
                heapq.heappush(open_set, (f_score, counter, neighbor))
                counter += 1
    
    return None
