clc;
clear;

% Initialize variables
points = [];

% Load and display image
try
    img1 = imread('museum.png');
catch
    error('Error: Could not load 1.png. Ensure the file exists in the working directory.');
end
[height, width, ~] = size(img1); % Get image dimensions
figure;
imshow(img1);
title('Select two points to define scale (origin: bottom-left)');

% Get two points for scaling
[x, y] = ginput(2);
if numel(x) < 2
    error('Error: Please select exactly two points.');
end

% Transform y-coordinates to bottom-left origin
y_transformed = height - y; % Bottom edge becomes y=0

% Plot selected points
hold on;
plot(x, y, 'ro', 'MarkerSize', 10, 'LineWidth', 2); % Plot in original image coords
hold off;

% Calculate pixel distance (unchanged, as distance is invariant)
pixelDistance = sqrt((x(2) - x(1))^2 + (y(2) - y(1))^2);

% Prompt for actual distance
actualDistance = input('Enter the actual distance between the two points (meters): ');
if ~isnumeric(actualDistance) || actualDistance <= 0
    error('Error: Actual distance must be a positive number.');
end

% Calculate scale (pixels per meter)
scale = pixelDistance / actualDistance;

% Loop to collect additional points
figure;
imshow(img1);
title('Click points to mark (press Enter to finish, origin: bottom-left)');
hold on;
pointCount = 0;
while true
    [x, y] = ginput(1);
    if isempty(x) || isempty(y)
        break; % Exit on Enter
    end
    % Transform y-coordinate to bottom-left origin
    y_transformed = height - y;
    points = [points; x, y_transformed]; % Store transformed coords (x, y_transformed)
    pointCount = pointCount + 1;
    
    % Plot point with label (in original image coords for display)
    scatter(x, y, 'filled', 'r');
    text(x + 5, y, sprintf('%d', pointCount), 'Color', 'white', 'FontSize', 10);
end
hold off;

% Convert to real-world coordinates
if ~isempty(points)
    points1 = points / scale; % Scale to meters
    % Create table and save to Excel
    T = table(points1(:,1), points1(:,2), 'VariableNames', {'X_meters', 'Y_meters'});
    try
        writetable(T, '11.xlsx');
        disp('Coordinates saved to 11.xlsx');
    catch
        error('Error: Could not write to 11.xlsx. Check permissions or file status.');
    end
else
    disp('No points selected.');
end