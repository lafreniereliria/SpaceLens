function spatial_analysis_system_new()
% 主系统初始化
fig = figure('Name','基于多维数据的建筑空间效能评估系统2.0',...
    'Position',[100 100 1000 650],...
    'MenuBar','none',...
    'NumberTitle','off');

% 全局数据结构
data_store = struct(...
    'layout_img', [], ...    % 空间图像
    'loc_data', [], ...     % 定位数据
    'behavior_data', [], ... % 行为数据
    'ques_data', [], ...     % 问卷数据
    'env_data', [], ...     % 环境数据
    'results', struct() ... % 分析结果
    );

% 创建GUI控件
create_controls(fig);
ax = axes('Parent',fig,'Position',[0.35 0.52 0.5 0.45]);%显示图像
ax1 = axes('Parent',fig,'Position',[0.35 0.04 0.5 0.4]);%显示柱状图
% 界面组件
    function create_controls(parent)
        % 数据载入面板
        uipanel('Parent',parent,'Title','数据载入','Position',[0.02 0.69 0.2 0.3]);
        uicontrol('Style','pushbutton','String','载入空间图像',...
            'Position',[60 595 120 30],'Callback',@(src,evt)load_layout);
        uicontrol('Style','pushbutton','String','导入定位数据',...
            'Position',[60 560 120 30],'Callback',@import_loc_data);
        uicontrol('Style','pushbutton','String','导入行为数据',...
            'Position',[60 525 120 30],'Callback',@import_behavior_data);
        uicontrol('Style','pushbutton','String','导入问卷数据',...
            'Position',[60 490 120 30],'Callback',@import_ques_data);
        uicontrol('Style','pushbutton','String','导入环境数据',...
            'Position',[60 455 120 30],'Callback',@import_env_data);
        % 分析功能面板
        analysis_panel = uipanel('Parent', parent, 'Title', '评价指标', ...
            'Position', [0.02 0.02 0.2 0.65], 'Units', 'normalized'); % 调整面板位置和大小

        analysis_btns = {
            {'到访频次', @show_visit_count}, ...
            {'使用时长', @show_usetime}, ...
            {'停留时长', @show_duration}, ...
            {'轨迹长度', @plot_trajectory}, ...
            {'移动速率', @show_movement_speed}, ...
            {'聚类程度', @show_clustering}, ...
            {'人员密度', @show_density}, ...
            {'开放程度', @show_openness}, ...
            {'拓扑关系', @show_topology}, ...
            {'差异系数', @show_difference}, ...
            {'行为人次', @behavior_number}, ...
            {'行为时长', @behavior_duration}, ...
            {'行为发生率', @behavior_frequency}, ...
            {'行为复合度', @behavior_degree}, ...
            {'功能利用率', @space_utilization}, ...
            {'整体满意度', @satisfaction}, ...
            {'空间满意度', @satisfaction_region}, ...
            {'环境参数', @show_Parameter}, ...
            };

        num_btns = length(analysis_btns);
        btn_height = 0.05; % 按钮高度占面板10%
        spacing = 0.01;   % 按钮间距2%

        for i = 1:num_btns
            if i<num_btns/2+1
                y_pos = 1 - (i-1)*(btn_height + spacing) - btn_height;
                uicontrol('Parent', analysis_panel, ...
                    'Style', 'pushbutton', ...
                    'String', analysis_btns{i}{1}, ...
                    'Units', 'normalized', ...
                    'Position', [0.1 y_pos 0.4 btn_height], ...
                    'Callback', analysis_btns{i}{2});
            else
                j=i-num_btns/2;
                y_pos = 1 - (j-1)*(btn_height + spacing) - btn_height;
                uicontrol('Parent', analysis_panel, ...
                    'Style', 'pushbutton', ...
                    'String', analysis_btns{i}{1}, ...
                    'Units', 'normalized', ...
                    'Position', [0.55 y_pos 0.4 btn_height], ...
                    'Callback', analysis_btns{i}{2});
            end
        end

        % 保存按钮面板
        uipanel('Parent',parent,'Title','输出控制','Position',[0.02 0.03 0.2 0.22]);

        uicontrol('Style','pushbutton','String',' 清除当前视图',...
            'Position',[60 110 120 30],'Callback',@clear_current_view);
        uicontrol('Style','pushbutton','String','保存当前视图',...
            'Position',[60 70 120 30],'Callback',@save_current_view);
        uicontrol('Style','pushbutton','String','导出所有数据',...
            'Position',[60 30 120 30],'Callback',@export_all_data);
    end
%% 图像载入模块
    function load_layout(~,~)
        [file, path] = uigetfile({'*.jpg;*.png','图像文件'});
        if ~isequal(file,0)
            axes(ax);
            % axes(ax1);
            data_store.layout_img = imread(fullfile(path, file));
            % data_store.layout_img1 = imread('2.jpg');
            % imshow(data_store.layout_img1, 'Parent', ax1);
            % title(ax1, '空间区域划分');
            imshow(data_store.layout_img, 'Parent', ax);
            title(ax, '空间图像');
        end
    end

%% 数据导入模块

% 定位数据
    function import_loc_data(~,~)
        [file, path] = uigetfile({'*.xls;*.xlsx','选择定位数据'});
        if ~isequal(file,0)
            try
                data = loadDataFile(fullfile(path, file));
                [isValid, missingFields] = validateLocationData(data);
                if isValid
                    data_store.loc_data = data;
                    msgbox('定位数据加载成功！');
                else
                    error('缺少必要字段: %s', strjoin(missingFields, ', '));
                end
            catch ME
                errordlg(['数据加载失败: ' ME.message]);
            end
        end
    end

%  行为数据
    function import_behavior_data(~,~)
        [file, path] = uigetfile({'*.xls;*.xlsx','选择行为数据'});
        if ~isequal(file,0)
            try
                data = loadDataFile(fullfile(path, file));
                [isValid, missingFields] = validateBehaviorData(data);
                if isValid
                    data_store.behavior_data = data;
                    msgbox('行为数据加载成功！');
                else
                    error('缺少必要字段: %s', strjoin(missingFields, ', '));
                end
            catch ME
                errordlg(['数据加载失败: ' ME.message]);
            end
        end
    end

%  问卷数据
    function import_ques_data(~,~)
        [file, path] = uigetfile({'*.xls;*.xlsx','选择问卷数据'});
        if ~isequal(file,0)
            try
                data = loadDataFile(fullfile(path, file));
                [isValid, missingFields] = validateQuesData(data);
                if isValid
                    data_store.ques_data = data;
                    msgbox('问卷数据加载成功！');
                else
                    error('缺少必要字段: %s', strjoin(missingFields, ', '));
                end
            catch ME
                errordlg(['数据加载失败: ' ME.message]);
            end
        end
    end

%  环境数据
    function import_env_data(~,~)
        [file, path] = uigetfile({'*.xls;*.xlsx','选择环境数据'});
        if ~isequal(file,0)
            try
                data = loadDataFile(fullfile(path, file));
                [isValid, missingFields] = validateEnvData(data);
                if isValid
                    data_store.env_data = data;
                    msgbox('环境数据加载成功！');
                else
                    error('缺少必要字段: %s', strjoin(missingFields, ', '));
                end
            catch ME
                errordlg(['数据加载失败: ' ME.message]);
            end
        end
    end

%%% 数据验证函数

% 定位数据
    function [isValid, missingFields] = validateLocationData(data)
        requiredFields = {'UserID', 'X', 'Y'};
        [isValid, missingFields] = validateDataFields(data, requiredFields);
    end

% 行为数据
    function [isValid, missingFields] = validateBehaviorData(data)
        requiredFields = {'X', 'Y', 'BehaviorNum'};
        [isValid, missingFields] = validateDataFields(data, requiredFields);
    end

% 问卷数据
    function [isValid, missingFields] = validateQuesData(data)
        requiredFields = {'UserNum', 'Satisfaction'};
        [isValid, missingFields] = validateDataFields(data, requiredFields);
    end

% 环境数据
    function [isValid, missingFields] = validateEnvData(data)
        requiredFields = {'X', 'Y','ParameterNum', 'Value'};
        [isValid, missingFields] = validateDataFields(data, requiredFields);
    end

    function [isValid, missingFields] = validateDataFields(data, requiredFields)
        if istable(data)
            actualFields = data.Properties.VariableNames;
        elseif isstruct(data)
            actualFields = fieldnames(data);
        else
            isValid = false;
            missingFields = requiredFields;
            return;
        end
        missingFields = setdiff(requiredFields, actualFields);
        isValid = isempty(missingFields);
    end
%% 分析可视化模块

%% A1到访频次
    function show_visit_count(~,~)
        if isempty(data_store.loc_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和定位数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        imshow(data_store.layout_img, 'Parent', ax);
        x=data_store.loc_data.X;
        y=data_store.loc_data.Y;
        region_ids = data_store.loc_data.Region;
        reg_ids = unique(region_ids);
        region_counts=zeros(size(reg_ids));
        for k = 1:length(reg_ids)
            % 数据提取
            pid = reg_ids(k);
            person_data =data_store.loc_data(region_ids==pid,:);
            per_id=person_data(:,1);
            region_counts(k)=height(per_id);%统计到访人次
            % region_counts(k)=height(unique(per_id));%统计到访人数
        end
        % 写入Excel文件
        data_table = table(reg_ids, region_counts, 'VariableNames', {'区域编号', '到访频次'});
        writetable(data_table, 'A1到访频次.xlsx');
        % 显示结果
        bar(region_counts(1:end-1), 'Parent', ax1);
        xlabel('区域编号');
        ylabel('到访人次');
        title(ax1,'各区域到访频次统计');
        set(ax1, 'XTickLabel', reg_ids(1:end-1));
        grid on;
      
        img=data_store.layout_img;
        if size(img, 3) == 3
            img1 = rgb2gray(img);
        end
        % 将图像二值化
        binaryImg = imbinarize(img1);
        % 栅格化热力图
        gridSize = 20;
        [imgHeight, imgWidth, ~] = size(img);
        % 初始化栅格到访频次矩阵
        numCols = ceil(imgWidth / gridSize);
        numRows = ceil(imgHeight / gridSize);
        visitFrequency = zeros(numRows, numCols);

        % 计算每个坐标对应的栅格索引，并更新到访频次
        for i = 1:length(x)
            % 计算栅格索引
            colIndex = ceil(x(i) / gridSize);
            rowIndex = ceil(y(i) / gridSize);

            % 检查索引是否在有效范围内
            if colIndex >= 1 && colIndex <= numCols && rowIndex >= 1 && rowIndex <= numRows
                visitFrequency(rowIndex, colIndex) = visitFrequency(rowIndex, colIndex) + 1;
            end
        end
        % 归一化到访频次矩阵，以便于可视化
        visitFrequencyNormalized = (visitFrequency - min(visitFrequency(:))) / (max(visitFrequency(:)) - min(visitFrequency(:)));
        % 将到访频次矩阵转换为热力图
        heatmap = ind2rgb(uint8(visitFrequencyNormalized * 255), jet(256));
        heatmapResized = imresize(heatmap, [imgHeight, imgWidth], 'nearest');
        % 创建一个半透明的热力图覆盖层
        alpha = 0.95; % 热力图的透明度
        heatmapOverlay = heatmapResized * alpha * 255; % 转换为与图像匹配的尺度
        % 将热力图叠加到原始图像上
        outputImage1 = double(img) * (1 - alpha) + heatmapOverlay; % 注意颜色范围匹配
        outputImage = uint8(outputImage1); % 转换为8位无符号整数
        mask = repmat(binaryImg, [1, 1, 3]); % 将二值图像扩展到与热力图相同的通道数
        maskedHeatmap = outputImage .* uint8(mask); % 应用掩码
        % 显示结果
        imshow(maskedHeatmap);
        title('空间到访频次');
        clim([min(visitFrequency(:)) max(visitFrequency(:))]); % 设置颜色条的范围
        myjet = jet;
        myjet(1,:) = [1 1 1];
        colormap(myjet);
        colorbar;
    end

%% A2使用时长
    function show_usetime(~,~)
        if isempty(data_store.loc_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和定位数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        % 提取数据
        x = data_store.loc_data.X;
        y = data_store.loc_data.Y;
        spaceIDs = data_store.loc_data.Region; % 空间编号
        timestamps = data_store.loc_data.Timestamp; % 定位时刻
        t = data_store.loc_data.t; % 时长（秒）
        % 确保 timestamps 是 datetime 类型
        if iscell(timestamps)
            timestamps = datetime(timestamps, 'InputFormat', 'HH:mm:ss');
        elseif ischar(timestamps) || isstring(timestamps)
            timestamps = datetime(timestamps, 'InputFormat', 'HH:mm:ss');
        end
        if iscell(t)
            t = cellfun(@str2double, t);
        end

        % 计算时间区间：[start_time, end_time]
        endTimes = timestamps + seconds(t);
        timeIntervals = [timestamps, endTimes];

        % ===== 1. 按空间编号分组统计总使用时长 =====
        uniqueSpaces = unique(spaceIDs);
        totalDurations = zeros(size(uniqueSpaces));
        for i = 1:length(uniqueSpaces)
            currentSpace = uniqueSpaces(i);
            spaceIdx = (spaceIDs == currentSpace);
            spaceIntervals = timeIntervals(spaceIdx, :);

            if ~isempty(spaceIntervals)
                spaceIntervals = sortrows(spaceIntervals, 1);
                mergedIntervals = spaceIntervals(1, :);

                for j = 2:size(spaceIntervals, 1)
                    currentInterval = spaceIntervals(j, :);
                    lastMerged = mergedIntervals(end, :);

                    if currentInterval(1) <= lastMerged(2)
                        mergedIntervals(end, 2) = max(lastMerged(2), currentInterval(2));
                    else
                        mergedIntervals = [mergedIntervals; currentInterval];
                    end
                end
                totalDurations(i) = sum(seconds(mergedIntervals(:, 2) - mergedIntervals(:, 1)));
            end
        end

        % 写入Excel文件
        data_table = table(uniqueSpaces, totalDurations, 'VariableNames', {'区域编号', '使用时长'});
        writetable(data_table, 'A2使用时长.xlsx');
        % 显示空间使用时长条形图
        bar(totalDurations(1:end-1), 'Parent', ax1);
        title(ax1,'空间使用时长(s)');
        set(ax1, 'XTickLabel', uniqueSpaces(1:end-1));
        grid on;

        % ===== 2. 栅格化热力图可视化 =====
        img = data_store.layout_img;
        imshow(img, 'Parent', ax);
        if size(img, 3) == 3
            imgGray = rgb2gray(img);
        else
            imgGray = img;
        end
        binaryImg = imbinarize(imgGray); % 二值掩码（用于排除背景）

        % 栅格参数
        gridSize = 20; % 栅格大小（像素）
        [imgHeight, imgWidth] = size(imgGray);
        numCols = ceil(imgWidth / gridSize);
        numRows = ceil(imgHeight / gridSize);
        gridUsageTime = zeros(numRows, numCols); % 存储每个栅格的总使用时长

        % 初始化栅格时间区间
        gridTimeIntervals = cell(numRows, numCols);

        % 遍历定位点，记录每个栅格的时间区间
        for i = 1:length(x)
            colIndex = min(max(1, ceil(x(i) / gridSize)), numCols); % 边界检查
            rowIndex = min(max(1, ceil(y(i) / gridSize)), numRows);

            if binaryImg(round(y(i)), round(x(i))) % 仅统计在前景区域内的点
                startTime = timestamps(i);
                endTime = startTime + seconds(t(i));

                if isempty(gridTimeIntervals{rowIndex, colIndex})
                    gridTimeIntervals{rowIndex, colIndex} = [startTime, endTime];
                else
                    gridTimeIntervals{rowIndex, colIndex} = [gridTimeIntervals{rowIndex, colIndex}; startTime, endTime];
                end
            end
        end

        % 合并每个栅格的时间区间并计算总时长
        for row = 1:numRows
            for col = 1:numCols
                intervals = gridTimeIntervals{row, col};
                if ~isempty(intervals)
                    intervals = sortrows(intervals, 1);
                    mergedIntervals = intervals(1, :);

                    for i = 2:size(intervals, 1)
                        lastInterval = mergedIntervals(end, :);
                        currentInterval = intervals(i, :);

                        if currentInterval(1) <= lastInterval(2)
                            mergedIntervals(end, 2) = max(lastInterval(2), currentInterval(2));
                        else
                            mergedIntervals = [mergedIntervals; currentInterval];
                        end
                    end
                    gridUsageTime(row, col) = sum(seconds(mergedIntervals(:, 2) - mergedIntervals(:, 1)));
                end
            end
        end

         % 归一化栅格数据并生成热力图
        visitFrequencyNormalized = (gridUsageTime - min(gridUsageTime(:))) / (max(gridUsageTime(:)) - min(gridUsageTime(:)) + eps);
        heatmap = ind2rgb(uint8(visitFrequencyNormalized * 255), jet(256));
        heatmapResized = imresize(heatmap, [imgHeight, imgWidth], 'nearest');

        % 创建一个半透明的热力图覆盖层
        alpha = 0.95; % 热力图的透明度
        heatmapOverlay = heatmapResized * alpha * 255; % 转换为与图像匹配的尺度

        % 将热力图叠加到原始图像上
        outputImage1 = double(img) * (1 - alpha) + heatmapOverlay; % 注意颜色范围匹配
        outputImage = uint8(outputImage1); % 转换为8位无符号整数
        mask = repmat(binaryImg, [1, 1, 3]); % 将二值图像扩展到与热力图相同的通道数
        maskedHeatmap = outputImage .* uint8(mask); % 应用掩码

        % 显示结果
        imshow(maskedHeatmap);
        title('空间使用时长(s)');
        clim([min(gridUsageTime(:)) max(gridUsageTime(:))]); % 设置颜色条的范围
        myjet = jet;
        myjet(1,:) = [1 1 1];
        colormap(myjet);
        colorbar;  
    end

%% A3移动速率
    function show_movement_speed(~,~)
        if isempty(data_store.loc_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和定位数据！');
            return;
        end
        data=data_store.loc_data;
        cla(ax, 'reset')
        cla(ax1, 'reset')
        imshow(data_store.layout_img, 'Parent', ax);
        x_coords=data.X;
        y_coords=data.Y;
        t=data.t; % 每个点的停留时长
        person_ids = data.UserID;
        per_ids = unique(person_ids);
        region_ids = data.Region;
        reg_ids = unique(region_ids);
        region_counts=zeros(size(reg_ids));
        ra=18.06; % 图像与实际尺寸比例
        img=data_store.layout_img;
        %各区域停留时长
        for k = 1:length(reg_ids)
            % 数据提取
            pid = reg_ids(k);
            person_data =data_store.loc_data(region_ids==pid,:);
            region_counts(k)=sum(person_data{:,5});
        end
        %各区域流线长度
        total_lengths = zeros(size(per_ids));
        region_stats = cell(size(per_ids));
        % 遍历每个人员
        for k = 1:size(per_ids,1)
            % 数据提取
            pid = per_ids(k);
            person_data =data(data.UserID==pid,:);
            x = person_data.X;
            y = person_data.Y;
            regions= person_data.Region;

            % 新增步骤：去除连续静止点（阈值可调）
            [x, y, regions] = removeStaticPoints(x, y, regions, 0.001); % 0.1为坐标变化阈值

            % 轨迹处理
            if length(x) > 1
                % 计算轨迹长度
                dx = diff(x); dy = diff(y);
                total_lengths(k) = sum(sqrt(dx.^2 + dy.^2));
                total_lengths(k)=total_lengths(k)/ra;
            else
                total_lengths(k) = 0;
            end

            % 区域统计（优化分配逻辑）
            region_map = containers.Map('KeyType', 'double', 'ValueType', 'double');
            if length(x) >= 2
                for i = 1:length(x)-1
                    seg_dist = norm([x(i+1)-x(i), y(i+1)-y(i)])/ra;
                    reg_sequence = getTransitionRegions(regions(i), regions(i+1));
                    distributeDistance(region_map, seg_dist, reg_sequence);
                end
            end
            region_stats{k} = region_map;
        end

        % 获取所有区域编号（按升序排列）
        all_regions = unique(data.Region);
        sorted_regions = sort(all_regions);

        % 创建结果表格
        result_table = array2table(zeros(length(per_ids), length(sorted_regions)));
        for k = 1:length(per_ids)
            pid = per_ids(k);
            result_table.PersonID(k) = pid;

            % 填充区域数据
            current_map = region_stats{k};
            for r = 1:length(sorted_regions)
                reg = sorted_regions(r);
                if current_map.isKey(reg)
                    result_table{k, r} = current_map(reg);
                else
                    result_table{k, r} = 0;
                end
            end

            % 添加总长度列
            result_table.TotalLength(k) = total_lengths(k);
        end

        % % 调整列顺序（将总长度放在最后）
        result_table = [result_table(:,1:end-1), result_table(:,end)];

        %% 统计各区域流线长度
        reg_total=zeros(length(sorted_regions),1);
        for tt = 1:length(sorted_regions)
            reg_total(tt)= sum(result_table{:, tt});
        end
        
        mean_v=reg_total./region_counts;
        % 写入Excel文件
        data_table = table(reg_ids, mean_v, 'VariableNames', {'区域编号', '移动速率'});
        writetable(data_table, 'A3移动速率.xlsx');
        %显示结果
        bar(mean_v(1:end-1), 'Parent', ax1);
        title(ax1,'各区域平均移动速率(m/s)');
        set(ax1, 'XTickLabel', reg_ids(1:end-1));
        grid on;
        % 添加标准线
        totalTime=sum(region_counts(1:end-1));
        tatalLen=sum(reg_total(1:end-1)); 
        stander=tatalLen/totalTime;
        yline(ax1,stander, 'r--', '整个空间平均速率', 'LineWidth', 2, 'LabelVerticalAlignment', 'bottom');
 
        if size(img, 3) == 3
            img1 = rgb2gray(img);
        end
                % 将图像二值化
        binaryImg = imbinarize(img1);
        [image_width,image_height,~] =size(img);
        interp_density = 10;  % 每段轨迹插值点数
        smooth_factor = 0.1;  % 平滑系数（0-1）
        % 定义固定栅格尺寸（单位：与坐标相同）
        grid_width = 20;   % 栅格宽度
        grid_height = 20;  % 栅格高度
        % 计算栅格范围
        x_min = 1;
        y_min = 1;
        % 生成栅格边缘
        x_edges = 1:grid_width:image_width;
        y_edges = 1:grid_height:image_height;
        % 初始化热力矩阵
        num_x_bins = length(x_edges);
        num_y_bins = length(y_edges);
        heatmap_matrix = zeros(num_x_bins, num_y_bins); %初始化流线长度
        heatmap_matrix1= zeros(num_x_bins, num_y_bins); %初始化停留时长
        %% 计算停留时长(s)
        for i = 1:length(x_coords)
            % 计算栅格索引
            colIndex = ceil(x_coords(i) / grid_width);
            rowIndex = ceil(y_coords(i) / grid_height);
            % 检查索引是否在有效范围内
            if colIndex >= 1 && colIndex <= num_y_bins && rowIndex >= 1 && rowIndex <= num_x_bins
                heatmap_matrix1(rowIndex, colIndex) = heatmap_matrix1(rowIndex, colIndex) + 1;
            end
        end
        heatmap_matrix1=heatmap_matrix1*10;
        %% 计算流线长度(m)
        unique_ids = unique(person_ids);
        for p = 1:length(unique_ids)
            current_id = unique_ids(p);
            mask = (person_ids == current_id);
            raw_x = x_coords(mask);
            raw_y = y_coords(mask);
            % 轨迹插值和平滑处理
            if length(raw_x) > 3
                % 样条插值
                t = 1:length(raw_x);
                tt = linspace(1, length(raw_x), interp_density*length(raw_x));
                interp_x = csaps(t, raw_x, smooth_factor, tt);
                interp_y = csaps(t, raw_y, smooth_factor, tt);
            else
                % 简单线性插值（当点数不足时）
                tt = linspace(1, length(raw_x), interp_density*length(raw_x));
                interp_x = interp1(1:length(raw_x), raw_x, tt, 'linear');
                interp_y = interp1(1:length(raw_x), raw_y, tt, 'linear');
            end
            % 处理插值后的轨迹段
            for k = 1:(length(interp_x)-1)
                x0 = interp_x(k);
                y0 = interp_y(k);
                x1 = interp_x(k+1);
                y1 = interp_y(k+1);
                % 计算线段参数
                dx = x1 - x0;
                dy = y1 - y0;
                seg_length = norm([dx, dy]);
                if seg_length == 0
                    continue;
                end
                % 参数化处理线段
                t_current = 0;
                while t_current < 1
                    % 当前栅格索引
                    i = floor((x0 + t_current*dx - x_min)/grid_width) + 1;
                    j = floor((y0 + t_current*dy - y_min)/grid_height) + 1;
                    % 计算栅格边界
                    x_low = x_min + (i-1)*grid_width;
                    x_high = x_low + grid_width;
                    y_low = y_min + (j-1)*grid_height;
                    y_high = y_low + grid_height;
                    % 计算线段与栅格的交点
                    tx = [(x_low - x0)/dx, (x_high - x0)/dx];
                    ty = [(y_low - y0)/dy, (y_high - y0)/dy];
                    % 筛选有效t值
                    valid_t = [tx, ty];
                    valid_t = valid_t(valid_t > t_current & valid_t <= 1);
                    t_end = min([valid_t, 1]);
                    % 更新热力图
                    if i >=1 && i <= num_y_bins && j >=1 && j <= num_x_bins
                        heatmap_matrix(j, i) = heatmap_matrix(j, i) + seg_length*(t_end - t_current);
                    end
                    t_current = t_end;
                end
            end
        end
        heatmap_matrix=heatmap_matrix/ra; %流线长度（米）
        heatmap_matrix=heatmap_matrix./heatmap_matrix1;
        heatmap_matrix(heatmap_matrix == 0 | heatmap_matrix1 == 0) = 0;
        % 归一化到访频次矩阵，以便于可视化
        heatmap_matrixNormalized = (heatmap_matrix - min(heatmap_matrix(:))) / (max(heatmap_matrix(:)) - min(heatmap_matrix(:)));
        % 将到访频次矩阵转换为热力图（使用伪彩色）
        heatmap = ind2rgb(uint8(heatmap_matrixNormalized * 255), jet(256));
        % 调整热力图大小以匹配图像栅格划分
        heatmapResized = imresize(heatmap, [image_width,image_height], 'nearest');
        % 创建一个半透明的热力图覆盖层
        alpha = 0.95; % 热力图的透明度
        heatmapOverlay = heatmapResized * alpha * 255; % 转换为与图像匹配的尺度
        % 将热力图叠加到原始图像上
        outputImage1 = double(img) * (1 - alpha) + heatmapOverlay; % 注意颜色范围匹配
        outputImage = uint8(outputImage1); % 转换为8位无符号整数
        mask = repmat(binaryImg, [1, 1, 3]); % 将二值图像扩展到与热力图相同的通道数
        maskedHeatmap = outputImage .* uint8(mask); % 应用掩码
        % 显示结果
        imshow(maskedHeatmap);
        title('空间人员移动速率(m/s)');
        clim([min(heatmap_matrix(:)) max(heatmap_matrix(:))]); % 设置颜色条的范围
        myjet = jet;
        myjet(1,:) = [1 1 1];
        colormap(myjet);
        colorbar;
    end

%% A4停留时长
    function show_duration(~,~)
        if isempty(data_store.loc_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和定位数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        imshow(data_store.layout_img, 'Parent', ax);
        x=data_store.loc_data.X;
        y=data_store.loc_data.Y;
        t= data_store.loc_data.t;%每个点的停留时长
        region_ids = data_store.loc_data.Region;
        reg_ids = unique(region_ids);
        region_counts=zeros(size(reg_ids));
        for k = 1:length(reg_ids)
            % 数据提取
            pid = reg_ids(k);
            person_data =data_store.loc_data(region_ids==pid,:);
            region_counts(k)=sum(person_data{:,5});
        end
        % 写入Excel文件
        data_table = table(reg_ids, region_counts, 'VariableNames', {'区域编号', '停留时长'});
        writetable(data_table, 'A4停留时长.xlsx');
        %显示结果
        bar(region_counts(1:end-1), 'Parent', ax1);
        xlabel('区域编号');
        ylabel('停留时长');
        title(ax1,'各区域停留时长统计(s)');
        set(ax1, 'XTickLabel', reg_ids(1:end-1));
        grid on;

        img = data_store.layout_img;
        % 转换图像为灰度
        if size(img, 3) == 3
            img1 = rgb2gray(img);
        else
            img1 = img;
        end

        % 将图像二值化
        binaryImg = imbinarize(img1);
        % 栅格化热力图
        gridSize = 20;
        [imgHeight, imgWidth, ~] = size(img);
        % 初始化栅格到访频次矩阵
        numCols = ceil(imgWidth / gridSize);
        numRows = ceil(imgHeight / gridSize);
        visitFrequency = zeros(numRows, numCols);

        % 计算每个坐标对应的栅格索引，并更新到访频次
        for i = 1:length(x)
            % 计算栅格索引
            colIndex = ceil(x(i) / gridSize);
            rowIndex = ceil(y(i) / gridSize);

            % 检查索引是否在有效范围内
            if colIndex >= 1 && colIndex <= numCols && rowIndex >= 1 && rowIndex <= numRows
                visitFrequency(rowIndex, colIndex) = visitFrequency(rowIndex, colIndex) + t(i);
            end
        end
        % 归一化到访频次矩阵，以便于可视化
        visitFrequencyNormalized = (visitFrequency - min(visitFrequency(:))) / (max(visitFrequency(:)) - min(visitFrequency(:)));
        % 将到访频次矩阵转换为热力图
        heatmap = ind2rgb(uint8(visitFrequencyNormalized * 255), jet(256));
        heatmapResized = imresize(heatmap, [imgHeight, imgWidth], 'nearest');
        % 创建一个半透明的热力图覆盖层
        alpha = 0.95; % 热力图的透明度
        heatmapOverlay = heatmapResized * alpha * 255; % 转换为与图像匹配的尺度
        % 将热力图叠加到原始图像上
        outputImage1 = double(img) * (1 - alpha) + heatmapOverlay; % 注意颜色范围匹配
        outputImage = uint8(outputImage1); % 转换为8位无符号整数
        mask = repmat(binaryImg, [1, 1, 3]); % 将二值图像扩展到与热力图相同的通道数
        maskedHeatmap = outputImage .* uint8(mask); % 应用掩码
        % 显示结果
        imshow(maskedHeatmap);
        title('空间停留时长(s)');
        clim([min(visitFrequency(:)) max(visitFrequency(:))]); % 设置颜色条的范围
        myjet = jet;
        myjet(1,:) = [1 1 1];
        colormap(myjet);
        colorbar;
    end

%% A5空间聚类
    function show_clustering(~,~)
        if isempty(data_store.loc_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和定位数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1,'reset')
        imshow(data_store.layout_img, 'Parent', ax);
        x = data_store.loc_data.X;
        y = data_store.loc_data.Y;
        hold on;
        scatter(ax,x,y,10,'filled');
        title(ax,'空间人员定位散点图');
        hold on;
        data=[x,y];
        % 输入聚类数量
        % 创建带验证的输入对话框
        while true
            k = inputdlg('请输入聚类数量 k：', 'K-means参数设置');

            % 检查是否取消输入
            if isempty(k)
                error('用户取消了输入');
            end

            % 转换为数值并验证
            k = str2double(k{1});
            if ~isnan(k) && isreal(k) && k > 0 && rem(k,1) == 0
                break;
            else
                errordlg('输入必须为正整数！', '输入错误');
            end
        end
        [idx, centroids] = kmeans(data, k);

        %% 3. 可视化聚类结果
        gscatter(ax,data(:,1), data(:,2), idx); % 绘制聚类结果
        hold on;
        plot(ax,centroids(:,1), centroids(:,2), 'kx', 'MarkerSize', 15, 'LineWidth', 3, 'DisplayName', 'Centroids'); % 绘制聚类中心
        title(ax, ['K-means聚类结果（k=', num2str(k), ')']);
        legend(ax,'Location', 'best');

    end

%% A6空间人员密度
    function show_density(~,~)
        if isempty(data_store.loc_data)
            errordlg('请先载入建筑空间定位数据！');
            return;
        end
        ra=18.06; %图像与实际尺寸比例
        cla(ax, 'reset')
        cla(ax1, 'reset')
        %% 1. 读取Excel数据
        data=data_store.loc_data; 
        t= data.t;%每个点的停留时长
        region_ids = data.Region;
        timestamps = data.Timestamp; % 定位时刻
        % 确保 timestamps 是 datetime 类型
        if iscell(timestamps)
            timestamps = datetime(timestamps, 'InputFormat', 'HH:mm:ss');
        elseif ischar(timestamps) || isstring(timestamps)
            timestamps = datetime(timestamps, 'InputFormat', 'HH:mm:ss');
        end
        if iscell(t)
            t = cellfun(@str2double, t);
        end
       
        %% 2. 定义整点时间分段
        % 将时间对齐到整点（例如 08:15 → 08:00）
        timestamps1 = dateshift(timestamps, 'start', 'hour');

        % 生成唯一的整点时间列表（去重）
        uniqueHours = unique(timestamps1);

        % 定义时间分段边界（每个小时为一个区间）
        timeBins = [uniqueHours; max(uniqueHours) + hours(1)]; % 添加一个额外的上界

        %% 3. 统计每个整点时间段内各区域的人数（去重）
        % 分配每个时间点到对应的整点区间
        data.TimeBin = discretize(timestamps, timeBins);

        % 按整点时间段和区域统计人数（去重：同一人在同一区域同一时间段只计1次）
        [uniquePairs, ~, ic] = unique([data.TimeBin, region_ids], 'rows');
        personCounts = accumarray(ic, 1); % 计数

        % 转换为表格
        timeBinEdges = timeBins(uniquePairs(:,1));
        regionNumbers = uniquePairs(:,2);
        resultTable = table(timeBinEdges, regionNumbers, personCounts, ...
            'VariableNames', {'TimeStart', 'RegionID', 'PersonCount'});

        %% 4. 补全缺失的时间段和区域（填充为0）
        % 生成所有可能的整点时间段和区域组合
        allHours = uniqueHours';
        allRegions = unique(region_ids)';
        [allPairs.Time, allPairs.Region] = meshgrid(allHours, allRegions);
        allPairs = table(allPairs.Time(:), allPairs.Region(:), 'VariableNames', {'TimeStart', 'RegionID'});

        % 合并统计结果并补全缺失值
        fullResult = outerjoin(allPairs, resultTable, 'Keys', {'TimeStart', 'RegionID'}, 'MergeKeys', true);
        fullResult.PersonCount(isnan(fullResult.PersonCount)) = 0; % 缺失值填充为0

        % 按时间和区域排序
        fullResult = sortrows(fullResult, {'TimeStart', 'RegionID'});
        %% 5计算各区域面积
        data1 = readtable('region_coordinates.xlsx');
        % 提取唯一区域编号
        regionIDs = unique(data1{:, 1}); % 第一列是区域编号
        % 初始化存储面积的数组
        regionAreas = zeros(length(regionIDs), 2); % [区域编号, 面积]
        % 遍历每个区域，计算面积
        for i = 1:length(regionIDs)
            id = regionIDs(i);

            % 提取当前区域的坐标
            regionData = data1(data1{:, 1} == id, :); % 筛选当前区域的数据
            x = regionData{:, 2}; % 第二列是 x 坐标
            y = regionData{:, 3}; % 第三列是 y 坐标

            % 确保多边形闭合（首尾顶点相同）
            if x(1) ~= x(end) || y(1) ~= y(end)
                x = [x; x(1)];
                y = [y; y(1)];
            end

            % 计算面积（使用鞋带公式）
            area = 0.5 * abs(sum(x(1:end-1) .* y(2:end)) - sum(y(1:end-1) .* x(2:end)));
            % area = polyarea(x, y);
            % 存储结果
            regionAreas(i, :) = [id, area];
        end
        regionAreas=regionAreas(:,2)/ra/ra;  % 区域实际面积
        % regionAreas=[regionAreas([1,3:end]); 1]; % 删除区域2，补区域10的面积
        % 将结果保存到Excel
        writetable(fullResult, 'A6空间人员密度.xlsx');
        stackedData = unstack(fullResult, 'PersonCount', 'RegionID');
        stackedData = stackedData{:, 2:end-1}; % 提取数值部分
        bar(ax,uniqueHours, stackedData/sum(regionAreas), 'stacked');
        title(ax,'空间人员密度(人/㎡)');
        legend(ax,arrayfun(@(x) sprintf('区域 %d', x), unique(fullResult.RegionID), 'UniformOutput', false));
        grid on;

        %% 6. 显示结果
        % 输入区域编号
        while true
            k = inputdlg('请输入区域编号 k：', '区域编号');

            % 检查是否取消输入
            if isempty(k)
                error('用户取消了输入');
            end

            % 转换为数值并验证
            k = str2double(k{1});
            if ~isnan(k) && isreal(k) && k > 0 && rem(k,1) == 0
                break;
            else
                errordlg('输入必须为正整数！', '输入错误');
            end
        end
        targetRegion = k; % 选择要绘制的区域编号
        regionData = fullResult(fullResult.RegionID == targetRegion, :);
        bar(ax1,regionData.TimeStart, regionData.PersonCount/regionAreas(k));
        title(ax1,['空间中区域 ', num2str(targetRegion), '人员密度(人/㎡)']);
        grid on;
end

%% A7空间开放程度
    function show_openness(~,~)
        if isempty(data_store.loc_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和定位数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        ra=18.06; %图像与实际尺寸比例
        %% 计算各区域面积
        % 1. 读取数据
        data = readtable('region_coordinates.xlsx');

        % 2. 提取唯一区域编号
        regionIDs = unique(data{:, 1}); % 第一列是区域编号

        % 3. 初始化存储面积的数组
        regionAreas = zeros(length(regionIDs), 2); % [区域编号, 面积]

        % 4. 遍历每个区域，计算面积
        for i = 1:length(regionIDs)
            id = regionIDs(i);

            % 提取当前区域的坐标
            regionData = data(data{:, 1} == id, :); % 筛选当前区域的数据
            x = regionData{:, 2}; % 第二列是 x 坐标
            y = regionData{:, 3}; % 第三列是 y 坐标

            % 确保多边形闭合（首尾顶点相同）
            if x(1) ~= x(end) || y(1) ~= y(end)
                x = [x; x(1)];
                y = [y; y(1)];
            end

            % 计算面积（使用鞋带公式）
            area = 0.5 * abs(sum(x(1:end-1) .* y(2:end)) - sum(y(1:end-1) .* x(2:end)));
            % area = polyarea(x, y);
            % 存储结果
            regionAreas(i, :) = [id, area];
        end
        regionAreas=regionAreas(:,2)/ra/ra;  % 区域实际面积
        regionAreas=[regionAreas([1,3:end]); 1]; % 删除区域2，补区域10的面积
        x=data_store.loc_data.X;
        y=data_store.loc_data.Y;
        ids=data_store.loc_data.UserID;
        region_ids = data_store.loc_data.Region;
        reg_ids = unique(region_ids);
        region_counts=zeros(size(reg_ids));
        for k = 1:length(reg_ids)
            % 数据提取
            pid = reg_ids(k);
            person_data =data_store.loc_data(region_ids==pid,:);
            per_id=person_data(:,1);
            region_counts(k)=height(unique(per_id));
        end
        region_counts1=region_counts./regionAreas;
        % 写入Excel文件
        data_table = table(reg_ids, region_counts1, 'VariableNames', {'区域编号', '空间开放程度'});
        writetable(data_table, 'A7空间开放程度.xlsx');
        %显示结果
        bar(region_counts1(1:end-1), 'Parent', ax1);
        title(ax1,'各区域开放程度(人/㎡)');
        set(ax1, 'XTickLabel', reg_ids(1:end-1));
        grid on;
        % 添加标准线
        totalNum=height(unique(data_store.loc_data.UserID));
        tatalAre=sum(regionAreas(1:end-1)); 
        stander=totalNum/tatalAre;
        yline(ax1,stander, 'r--', '整个空间开放程度值', 'LineWidth', 2, 'LabelVerticalAlignment', 'bottom');
 
        img=data_store.layout_img;
        imshow(img, 'Parent', ax);
        if size(img, 3) == 3
            img1 = rgb2gray(img);
        end
        % 将图像二值化
        binaryImg = imbinarize(img1);
        % 栅格化热力图
        gridSize = 20;
        [imgHeight, imgWidth, ~] = size(img);
        % 初始化栅格到访人数矩阵
        numCols = ceil(imgWidth / gridSize);
        numRows = ceil(imgHeight / gridSize);
        uniquePersonCount = zeros(numRows, numCols); % 存储唯一人员数量
        visitFrequency = zeros(numRows, numCols);

        colIdx = ceil(x / gridSize);
        rowIdx = ceil(y / gridSize);

        % 2. 过滤越界坐标（超出图像范围的点）
        valid = (colIdx >= 1) & (colIdx <= numCols) & (rowIdx >= 1) & (rowIdx <= numRows);
        colIdx = colIdx(valid);
        rowIdx = rowIdx(valid);
        ids = ids(valid); % 同时过滤对应的人员ID

        % 3. 组合栅格索引和人员ID，用于唯一统计
        gridPersonPairs = [rowIdx, colIdx, ids]; % 每行格式：[栅格行, 栅格列, 人员ID]

        % 4. 使用 unique 统计每个栅格中的唯一人员数量
        [~, idx, ~] = unique(gridPersonPairs, 'rows', 'stable'); % 'stable'保持原始顺序
        uniqueGridPersonPairs = gridPersonPairs(idx, :);         % 去重后的栅格-人员对

        % 5. 按栅格索引分组统计
        [gridIndices, ~, ic] = unique(uniqueGridPersonPairs(:, 1:2), 'rows'); % 提取唯一栅格坐标
        counts = accumarray(ic, 1); % 统计每个栅格的唯一人员数量

        % 6. 填充结果矩阵
        uniquePersonCount = zeros(numRows, numCols);
        linearIdx = sub2ind([numRows, numCols], gridIndices(:, 1), gridIndices(:, 2));
        uniquePersonCount(linearIdx) = counts;

        % % --- 可选：统计总到访人次
        % for i = 1:length(x)
        %     if valid(i)
        %         visitFrequency(rowIdx(i), colIdx(i)) = visitFrequency(rowIdx(i), colIdx(i)) + 1;
        %     end
        % end

        visitFrequency=uniquePersonCount*ra*ra/gridSize/gridSize;
        % 归一化到访频次矩阵，以便于可视化
        visitFrequencyNormalized = (visitFrequency - min(visitFrequency(:))) / (max(visitFrequency(:)) - min(visitFrequency(:)));
        % 将到访频次矩阵转换为热力图
        heatmap = ind2rgb(uint8(visitFrequencyNormalized * 255), jet(256));
        heatmapResized = imresize(heatmap, [imgHeight, imgWidth], 'nearest');
        % 创建一个半透明的热力图覆盖层
        alpha = 0.95; % 热力图的透明度
        heatmapOverlay = heatmapResized * alpha * 255; % 转换为与图像匹配的尺度
        % 将热力图叠加到原始图像上
        outputImage1 = double(img) * (1 - alpha) + heatmapOverlay; % 注意颜色范围匹配
        outputImage = uint8(outputImage1); % 转换为8位无符号整数
        mask = repmat(binaryImg, [1, 1, 3]); % 将二值图像扩展到与热力图相同的通道数
        maskedHeatmap = outputImage .* uint8(mask); % 应用掩码
        % 显示结果
        imshow(maskedHeatmap);
        title('空间开放程度');
        clim([min(visitFrequency(:)) max(visitFrequency(:))]); % 设置颜色条的范围
        myjet = jet;
        myjet(1,:) = [1 1 1];
        colormap(myjet);
        colorbar;
    end

%% A8拓扑连接关系
    function show_topology(~,~)
        if isempty(data_store.loc_data)
            errordlg('请先载入建筑空间人员定位数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        imshow(data_store.layout_img, 'Parent', ax);
        x_coords=data_store.loc_data.X;
        y_coords=data_store.loc_data.Y;
        person_ids = data_store.loc_data.UserID;
        % 获取唯一的人员编号
        unique_ids = unique(person_ids);
        % 对每个人的定位数据进行插值
        for i = 1:length(unique_ids)
            current_id = unique_ids(i);
            % 提取当前人员的定位数据
            idx = person_ids == current_id;
            current_x = x_coords(idx);
            current_y = y_coords(idx);
            % 设置插值点数量
            num_points = 100;
            % 生成均匀分布的插值点
            t = linspace(1, length(current_x), num_points);
            % 使用一维插值，这里假设x和y的坐标是同步变化的，所以使用相同的t进行插值
            xi = interp1(1:length(current_x), current_x, t, 'linear');
            yi = interp1(1:length(current_y), current_y, t, 'linear');
            % 将插值结果存储为表
            smooth_table = table(repmat(current_id, num_points, 1), xi', yi', 'VariableNames', {'人员编号', '定位坐标X', '定位坐标Y'});
            smooth_data{i} = smooth_table;
        end
        % 将所有结果合并为一个表
        all_smooth_data = [];
        for i = 1:length(smooth_data)
            all_smooth_data = [all_smooth_data; smooth_data{i}];
        end
              
        %% 计算新坐标所在区域
        % 从 Excel 文件中读取不规则区域的坐标
        regions_filename = 'region_coordinates.xlsx';
        regionData = readcell(regions_filename, 'Range', 'A2'); % 跳过表头
        importedRegions = cell(0);
        currentRegion = [];
        currentRegionNum = NaN;
        for i = 1:size(regionData, 1)
            regionNum = regionData{i, 1};
            x = regionData{i, 2};
            y = regionData{i, 3};
            if isnan(regionNum) || isnan(x) || isnan(y)
                continue;  % 跳过无效数据
            end
            if isempty(currentRegion) || regionNum ~= currentRegionNum
                % 保存上一个区域
                if ~isempty(currentRegion)
                    importedRegions{end+1} = currentRegion;
                end
                % 开始新区域
                currentRegion = [x, y];
                currentRegionNum = regionNum;
            else
                % 继续添加当前区域顶点
                currentRegion = [currentRegion; x, y];
            end
        end
        % 保存最后一个区域
        if ~isempty(currentRegion)
            importedRegions{end+1} = currentRegion;
        end
        % 创建输出表格
        outputData =zeros(size(all_smooth_data, 1), 4);
        outputData(:,1:3) = table2array(all_smooth_data);  % 保留原始坐标
        % 遍历每个输入点进行区域判断
        for p = 1:size(all_smooth_data, 1)
            point = all_smooth_data{p, 2:3};
            regionIdx = 0;  % 默认不属于任何区域
            for r = 1:length(importedRegions)
                coords = importedRegions{r};
                % 使用射线法判断点是否在多边形内
                inPolygon = inpolygon(point(1), point(2), coords(:,1), coords(:,2));
                if inPolygon
                    regionIdx = r;
                    break;
                end
            end
            outputData(p, 4) = regionIdx;  % 记录区域编号
        end
        data = outputData;
        % 提取人员编号、坐标和区域编号
        personIDs = data(:, 1);
        coordinates = data(:, 3); % 实际代码中需要解析坐标，这里简化为直接读取
        zones = data(:,4);
        % 找到唯一的区域编号
        uniqueZones1 = unique(zones);
        uniqueZones=uniqueZones1 (uniqueZones1>0);
        numZones = size(uniqueZones,1);
        % 初始化区域转移矩阵
        transitionMatrix = zeros(numZones, numZones);
        % 遍历每个人员的定位记录
        for i = 1:size(data, 1) - 1
            if personIDs(i) == personIDs(i + 1) % 确保是同一个人的连续记录
                fromZone = zones(i);
                toZone = zones(i + 1);
                if fromZone ~= toZone % 只有区域变化时才记录
                    % 找到区域在uniqueZones中的索引
                    fromIdx = find(uniqueZones == fromZone);
                    toIdx = find(uniqueZones == toZone);
                    % 增加从fromZone到toZone的计数
                    transitionMatrix(fromIdx, toIdx) = transitionMatrix(fromIdx, toIdx) + 1;
                end
            end
        end
        % 写入Excel文件
        writematrix(transitionMatrix, 'A8空间拓扑连接关系.xlsx');
        % 绘制图形
        imagesc(transitionMatrix, 'Parent', ax);
        set(ax, 'XTickLabel', uniqueZones,'YTickLabel', uniqueZones);
        title(ax,'各区域人员到访关系');
        myjet = jet;
        myjet(1,:) = [1 1 1];
        colormap(myjet);
        colorbar;

        G = digraph(transitionMatrix, cellstr(num2str(uniqueZones)));
        in_degree = sum(transitionMatrix, 1)';       % 入度中心性（列求和）
        out_degree = sum(transitionMatrix, 2);      % 出度中心性（行求和）
        pr = centrality(G, 'pagerank');       % PageRank中心性
        betweenness = centrality(G, 'betweenness');  % 介数中心性
        plot(ax1,G,'NodeCData', pr, 'MarkerSize', 100*pr,'LineWidth', 1 + 3*G.Edges.Weight/max(G.Edges.Weight));                % 使用PageRank值着色
        colormap(jet);                       % 使用jet颜色映射
        % 设置图形标题和标签
        title(ax1,'空间区域拓扑连接度');

        % bar(ax1,pr);
        % set(ax1, 'XTickLabel',uniqueZones);
        % title(ax1,'各节点中心性');
        % xlabel(ax1,'节点');
        % ylabel(ax1,'得分');

    end

%% A9轨迹差异系数
    function show_difference(~,~)
        if isempty(data_store.loc_data)
            errordlg('请先载入建筑空间人员定位数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        data=data_store.loc_data;      
        ra=18.06; %图像与实际尺寸比例
        % 提取人员编号、x坐标和y坐标
        data_PersonID = data.UserID;
        person_ids = unique(data_PersonID);
        % 初始化统计存储
        total_lengths = zeros(size(person_ids));
        region_stats = cell(size(person_ids));
        % 遍历每个人员
        for k = 1:size(person_ids,1)
            % 数据提取
            pid = person_ids(k);
            person_data =data(data.UserID==pid,:);
            x = person_data.X;
            y = person_data.Y;
            regions= person_data.Region;

            % 新增步骤：去除连续静止点（阈值可调）
            [x, y, regions] = removeStaticPoints(x, y, regions, 0.001); % 0.1为坐标变化阈值

            % 轨迹处理
            if length(x) > 1
                % 计算轨迹长度
                dx = diff(x); dy = diff(y);
                total_lengths(k) = sum(sqrt(dx.^2 + dy.^2));
                total_lengths(k)=total_lengths(k)/ra;
            else
                total_lengths(k) = 0;
            end

            % 区域统计（优化分配逻辑）
            region_map = containers.Map('KeyType', 'double', 'ValueType', 'double');
            if length(x) >= 2
                for i = 1:length(x)-1
                    seg_dist = norm([x(i+1)-x(i), y(i+1)-y(i)])/ra;
                    reg_sequence = getTransitionRegions(regions(i), regions(i+1));
                    distributeDistance(region_map, seg_dist, reg_sequence);
                end
            end
            region_stats{k} = region_map;
        end

        % 获取所有区域编号（按升序排列）
        all_regions = unique(data.Region);
        sorted_regions = sort(all_regions);

        % 创建结果表格
        result_table = array2table(zeros(length(person_ids), length(sorted_regions)));
        for k = 1:length(person_ids)
            pid = person_ids(k);
            result_table.PersonID(k) = pid;

            % 填充区域数据
            current_map = region_stats{k};
            for r = 1:length(sorted_regions)
                reg = sorted_regions(r);
                if current_map.isKey(reg)
                    result_table{k, r} = current_map(reg);
                else
                    result_table{k, r} = 0;
                end
            end

            % 添加总长度列
            result_table.TotalLength(k) = total_lengths(k);
        end
        avglen = sum(total_lengths) / sum(total_lengths ~= 0);
        % % 调整列顺序（将总长度放在最后）
        result_table = [result_table(:,1:end-1), result_table(:,end)];

        %% 统计各区域流线长度
        reg_total=zeros(length(sorted_regions),1);
        for tt = 1:length(sorted_regions)
            reg_total(tt)= sum(result_table{:, tt});
            meanNonZero(tt)=sum(result_table{:, tt}) / sum(result_table{:, tt} ~= 0); 
        end
        meanNonZero1=meanNonZero/mean(meanNonZero(1:end-1));
        % 写入Excel文件
        data_table = table(sorted_regions, meanNonZero1', 'VariableNames', {'区域编号', '轨迹长度差异系数'});
        writetable(data_table, 'A9轨迹长度差异系数.xlsx');
        bar(meanNonZero1(1:end-1), 'Parent', ax1);
        title(ax1,'各区域流线长度差异系数');
        set(ax1, 'XTickLabel', sorted_regions(1:end-1));
        bar(total_lengths(1:end)/avglen, 'Parent', ax);
        title(ax,'人员流线长度差异系数');
        set(ax, 'XTickLabel', person_ids(1:end));
        grid on;
end

%% A10轨迹长度
    function plot_trajectory(~,~)
        if isempty(data_store.loc_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和定位数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        imshow(data_store.layout_img, 'Parent', ax);
        data=data_store.loc_data;
        userIDs = unique(data.UserID);
        numUsers = length(userIDs);
        hold on;
        %% 绘制人员流线轨迹
        colors =lines(numUsers); % 不同颜色区分人员
        % 遍历每个人员
        for k = 1:numUsers
            % 数据提取
            userData = data(data.UserID == userIDs(k), :);
            x = userData.X;
            y = userData.Y;

            % 参数化处理
            t = cumsum([0; sqrt(diff(x).^2 + diff(y).^2)]);

            % 样条插值
            tt = linspace(t(1), t(end), 1000);
            xx = spline(t, x, tt);
            yy = spline(t, y, tt);
            % 绘制轨迹
            plot(xx, yy, 'Color', colors(k,:), 'LineWidth', 0.5);
            scatter(x, y,3, colors(k,:), 'MarkerFaceColor', colors(k,:))
            title(ax,'人员流线轨迹图');
        end

        ra=18.06; %图像与实际尺寸比例
        % 提取人员编号、x坐标和y坐标
        data_PersonID = data.UserID;
        person_ids = unique(data_PersonID);
        % 初始化统计存储
        total_lengths = zeros(size(person_ids));
        region_stats = cell(size(person_ids));
        % 遍历每个人员
        for k = 1:size(person_ids,1)
            % 数据提取
            pid = person_ids(k);
            person_data =data(data.UserID==pid,:);
            x = person_data.X;
            y = person_data.Y;
            regions= person_data.Region;

            % 新增步骤：去除连续静止点（阈值可调）
            [x, y, regions] = removeStaticPoints(x, y, regions, 0.001); % 0.1为坐标变化阈值

            % 轨迹处理
            if length(x) > 1
                % 计算轨迹长度
                dx = diff(x); dy = diff(y);
                total_lengths(k) = sum(sqrt(dx.^2 + dy.^2));
                total_lengths(k)=total_lengths(k)/ra;
            else
                total_lengths(k) = 0;
            end

            % 区域统计（优化分配逻辑）
            region_map = containers.Map('KeyType', 'double', 'ValueType', 'double');
            if length(x) >= 2
                for i = 1:length(x)-1
                    seg_dist = norm([x(i+1)-x(i), y(i+1)-y(i)])/ra;
                    reg_sequence = getTransitionRegions(regions(i), regions(i+1));
                    distributeDistance(region_map, seg_dist, reg_sequence);
                end
            end
            region_stats{k} = region_map;
        end

        % 获取所有区域编号（按升序排列）
        all_regions = unique(data.Region);
        sorted_regions = sort(all_regions);

        % 创建结果表格
        result_table = array2table(zeros(length(person_ids), length(sorted_regions)));
        for k = 1:length(person_ids)
            pid = person_ids(k);
            result_table.PersonID(k) = pid;

            % 填充区域数据
            current_map = region_stats{k};
            for r = 1:length(sorted_regions)
                reg = sorted_regions(r);
                if current_map.isKey(reg)
                    result_table{k, r} = current_map(reg);
                else
                    result_table{k, r} = 0;
                end
            end

            % 添加总长度列
            result_table.TotalLength(k) = total_lengths(k);
        end

        % % 调整列顺序（将总长度放在最后）
        result_table = [result_table(:,1:end-1), result_table(:,end)];

        %% 统计各区域流线长度
        reg_total=zeros(length(sorted_regions),1);
        meanNonZero=zeros(length(sorted_regions),1);
        for tt = 1:length(sorted_regions)
            reg_total(tt)= sum(result_table{:, tt});
            meanNonZero(tt)=sum(result_table{:, tt}) / sum(result_table{:, tt} ~= 0); 
        end
        % 写入Excel文件
        data_table = table(sorted_regions, reg_total,meanNonZero, 'VariableNames', {'区域编号', '区域轨迹长度', '人员平均轨迹长度'});
        writetable(data_table, 'A10轨迹长度.xlsx');
        %显示结果
        bar(reg_total(1:end-1), 'Parent', ax1);
        title(ax1,'各区域流线长度(m)');
        set(ax1, 'XTickLabel', sorted_regions(1:end-1));
        % bar(meanNonZero(1:end-1), 'Parent', ax1);
        % title(ax1,'各区域人员平均流线长度(m)');
        % set(ax1, 'XTickLabel', sorted_regions(1:end-1));
    end

%% 辅助函数
% 智能去除静止点
function [x_new, y_new, reg_new] = removeStaticPoints(x, y, reg, thresh)
    keep_idx = true(size(x));
    for i = 2:length(x)
        % 判断坐标变化是否超过阈值
        if norm([x(i)-x(i-1), y(i)-y(i-1)]) < thresh
            keep_idx(i) = false;
        end
    end
    x_new = x(keep_idx);
    y_new = y(keep_idx);
    reg_new = reg(keep_idx);

    % 保证至少保留首尾点
    if length(x_new) < 2 && length(x) >= 1
        x_new = [x(1); x(end)];
        y_new = [y(1); y(end)];
        reg_new = [reg(1); reg(end)];
    end
end

% 处理区域过渡
function reg_seq = getTransitionRegions(start_reg, end_reg)
    if start_reg == end_reg
        reg_seq = {start_reg, 1}; % [区域，权重]
    else
        reg_seq = {start_reg, 0.5; end_reg, 0.5};
    end
end

% 距离分配
function distributeDistance(map, dist, reg_seq)
    for i = 1:size(reg_seq,1)
        reg = reg_seq{i,1};
        ratio = reg_seq{i,2};
        if map.isKey(reg)
            map(reg) = map(reg) + dist*ratio;
        else
            map(reg) = dist*ratio;
        end
    end
end

%% B5环境参数
function show_Parameter(~,~)
        if isempty(data_store.env_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和环境数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        imshow(data_store.layout_img, 'Parent', ax);
        hold on
        labels = {'温度','湿度','光照','风速','噪声'};%1.温度 2.湿度 3.光照 4.风速 5.噪声
        % 输入区域编号
        while true
            k = inputdlg('请输入参数编号（1.温度 2.湿度 3.光照 4.风速 5.噪声）', '区域编号');

            % 检查是否取消输入
            if isempty(k)
                error('用户取消了输入');
            end

            % 转换为数值并验证
            k = str2double(k{1});
            if ~isnan(k) && isreal(k) && k > 0 && rem(k,1) == 0
                break;
            else
                errordlg('输入必须为正确的参数编号！', '输入错误');
            end
        end
        mask = data_store.env_data.ParameterNum == k;
        X = data_store.env_data.X(mask);
        Y = data_store.env_data.Y(mask);
        values = data_store.env_data.Value(mask);
        % 检查是否有有效数据
        if isempty(X)
            errordlg('当前参数无有效数据！');
            return;
        end
        scatter(ax, X, Y, 20,'r','filled');
        title(ax, '参数测点位置');
        % 图像尺寸信息
        img = data_store.layout_img;
        imshow(img, 'Parent', ax1);
        % 将图像转换为灰度图
        if size(img, 3) == 3
            img1 = rgb2gray(img);
        end
        % 将图像二值化
        binaryImg = imbinarize(img1);
        [rows, cols] = size(binaryImg);
        x_coords = linspace(min(X), max(X), cols);
        y_coords = linspace(min(Y), max(Y), rows);
        [X_grid, Y_grid] = meshgrid(x_coords, y_coords);
        F = scatteredInterpolant(X, Y, values, 'natural','none');
        % 生成插值结果
        interpValues = F(X_grid, Y_grid);
        % 应用空间掩膜
        maskedValues = interpValues;
        maskedValues(~binaryImg) = NaN;
        % maskedValues(maskedValues<500)=500;
        % 可视化
        imagesc(ax1,maskedValues);
        clim([min(maskedValues(:))*0.05 max(maskedValues(:))]); % 设置颜色条的范围
        myjet = jet;
        myjet(1,:) = [1 1 1];
        colormap(myjet);
        colorbar(ax1);
        title(ax1,[labels{k} '热力图']);
    end
    
%% C1行为发生人次
    function behavior_number(~,~)
        if isempty(data_store.behavior_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和行为数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        data=data_store.behavior_data;
        xCoords = data.X;   % X坐标
        yCoords = data.Y;   % Y坐标
        behaviorTypes = data.BehaviorNum; % 行为类型
        labels = data.behaviortype;
        labels =unique(labels);
        % 定义行为类型和颜色
        uniqueBehaviors = unique(behaviorTypes);
        imshow(data_store.layout_img, 'Parent', ax);
        hold on;
        % 在空间图像上绘制行为分布
        for i = 1:length(uniqueBehaviors)
            % 当前行为类型
            behavior = uniqueBehaviors(i);
            sy = behaviorTypes == behavior;  % 提取行为编号的数据
            % 绘制当前行为类型的点
            scatter(xCoords(sy), yCoords(sy), 20, 'filled');
        end
        % 添加图例和标签
        legend(ax,labels, 'Location', 'best');
        title(ax, '各行为分布图');

        regions = data.Region;
        actions=data.BehaviorNum;
        durations =data.t;
        unique_regions = unique(regions);
        unique_actions = unique(actions);
        count_matrix = zeros(length(unique_regions), length(unique_actions));
        duration_matrix = zeros(length(unique_regions), length(unique_actions));
        for i = 1:length(unique_regions)
            for j = 1:length(unique_actions)
                region_mask = (regions == unique_regions(i));
                action_mask = (actions == unique_actions(j));
                count_matrix(i, j) = sum(region_mask & action_mask);
                duration_matrix(i, j) = sum(durations(region_mask & action_mask));
            end
        end
        % 写入Excel文件
        data_table = table(unique_regions, count_matrix);
        writetable(data_table, 'C1行为发生人次.xlsx');
        %显示
        bar(ax1,unique_regions, count_matrix, 'stacked');
        title(ax1,'区域中各行为人次');
        legend(ax1,labels, 'Location', 'best');
        % 输入行为编号
        while true
            k = inputdlg('请输入行为编号（1.休闲娱乐 2.吸烟 3.其他）', '行为编号');

            % 检查是否取消输入
            if isempty(k)
                error('用户取消了输入');
            end

            % 转换为数值并验证
            k = str2double(k{1});
            if ~isnan(k) && isreal(k) && k > 0 && rem(k,1) == 0
                break;
            else
                errordlg('输入必须为正确的行为编号！', '输入错误');
            end
        end

        mask = data.BehaviorNum == k;
        X = data.X(mask);
        Y = data.Y(mask);
        % 检查是否有有效数据
        if isempty(X)
            errordlg('当前行为类型无有效数据！');
            return;
        end
        % 图像尺寸信息
        img = data_store.layout_img;
        cla(ax, 'reset')
        imshow(img, 'Parent', ax);
        % 将图像转换为灰度图
        if size(img, 3) == 3
            img1 = rgb2gray(img);
        end
        % 将图像二值化
        binaryImg = imbinarize(img1);
        grid=200;
        % 在空间图像上绘制行为分布
        [xq, yq] = meshgrid(linspace(1, size(binaryImg, 2), grid), linspace(1, size(binaryImg, 1), grid));
        xy = [X, Y];
        f = ksdensity(xy, [xq(:), yq(:)]);
        f = reshape(f, size(xq));
        % 归一化密度值到 0-1 范围
        f_normalized = (f - min(f(:))) / (max(f(:)) - min(f(:)));
        % 将热力图转换为图像格式
        heatmapImage = ind2rgb(im2uint8(f_normalized), jet(256));
        % 调整热力图大小以匹配背景图像（假设背景图像大小已知）
        heatmapImageResized = imresize(heatmapImage, size(binaryImg(:,:,1))); % 假设是 RGB，取一个通道的大小
        % 创建掩码，只在二值图像为1的区域显示热力图
        mask = repmat(binaryImg, [1, 1, 3]); % 将二值图像扩展到与热力图相同的通道数
        maskedHeatmap = heatmapImageResized .* mask; % 应用掩码
        % 将处理后的热力图叠加到二值图像上（或者直接显示掩码后的热力图）
        % 这里选择直接显示掩码后的热力图
        imshow(maskedHeatmap);
        myjet = jet;
        myjet(1,:) = [1 1 1];
        colormap(myjet);
        colorbar;
        title([labels{k} '行为分布热力图']);
    end

%% C2行为时长
    function behavior_duration(~,~)
        if isempty(data_store.behavior_data) || isempty(data_store.layout_img)
            errordlg('请先载入建筑空间图像和行为数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        data=data_store.behavior_data;
        labels = data.behaviortype;
        labels =unique(labels);
        regions = data.Region;
        actions=data.BehaviorNum;
        durations =data.t;
        unique_regions = unique(regions);
        unique_actions = unique(actions);
        count_matrix = zeros(length(unique_regions), length(unique_actions));
        duration_matrix = zeros(length(unique_regions), length(unique_actions));
        for i = 1:length(unique_regions)
            for j = 1:length(unique_actions)
                region_mask = (regions == unique_regions(i));
                action_mask = (actions == unique_actions(j));
                count_matrix(i, j) = sum(region_mask & action_mask);
                duration_matrix(i, j) = sum(durations(region_mask & action_mask));
            end
        end
        % 写入Excel文件
        data_table = table(unique_regions, duration_matrix);
        writetable(data_table, 'C2行为发生时长.xlsx');
        bar(ax1,unique_regions, duration_matrix, 'stacked');
        title(ax1,'区域中各行为时长(s)');
        legend(ax1,labels, 'Location', 'best');
        % 输入行为编号
        while true
            k = inputdlg('请输入行为编号（1.休闲娱乐 2.吸烟 3.其他）', '行为编号');

            % 检查是否取消输入
            if isempty(k)
                error('用户取消了输入');
            end

            % 转换为数值并验证
            k = str2double(k{1});
            if ~isnan(k) && isreal(k) && k > 0 && rem(k,1) == 0
                break;
            else
                errordlg('输入必须为正确的行为编号！', '输入错误');
            end
        end

        mask = data.BehaviorNum == k;
        x = data.X(mask);
        y = data.Y(mask);
        t = data.t(mask);
        img = data_store.layout_img;
        % 转换图像为灰度
        if size(img, 3) == 3
            img1 = rgb2gray(img);
        else
            img1 = img;
        end

        % 将图像二值化
        binaryImg = imbinarize(img1);
        % 栅格化热力图
        gridSize = 20;
        [imgHeight, imgWidth, ~] = size(img);
        % 初始化栅格到访频次矩阵
        numCols = ceil(imgWidth / gridSize);
        numRows = ceil(imgHeight / gridSize);
        visitFrequency = zeros(numRows, numCols);

        % 计算每个坐标对应的栅格索引，并更新到访频次
        for i = 1:length(x)
            % 计算栅格索引
            colIndex = ceil(x(i) / gridSize);
            rowIndex = ceil(y(i) / gridSize);

            % 检查索引是否在有效范围内
            if colIndex >= 1 && colIndex <= numCols && rowIndex >= 1 && rowIndex <= numRows
                visitFrequency(rowIndex, colIndex) = visitFrequency(rowIndex, colIndex) + t(i);
            end
        end
        % 归一化到访频次矩阵，以便于可视化
        visitFrequencyNormalized = (visitFrequency - min(visitFrequency(:))) / (max(visitFrequency(:)) - min(visitFrequency(:)));
        % 将到访频次矩阵转换为热力图
        heatmap = ind2rgb(uint8(visitFrequencyNormalized * 255), jet(256));
        heatmapResized = imresize(heatmap, [imgHeight, imgWidth], 'nearest');
        % 创建一个半透明的热力图覆盖层
        alpha = 0.95; % 热力图的透明度
        heatmapOverlay = heatmapResized * alpha * 255; % 转换为与图像匹配的尺度
        % 将热力图叠加到原始图像上
        outputImage1 = double(img) * (1 - alpha) + heatmapOverlay; % 注意颜色范围匹配
        outputImage = uint8(outputImage1); % 转换为8位无符号整数
        mask = repmat(binaryImg, [1, 1, 3]); % 将二值图像扩展到与热力图相同的通道数
        maskedHeatmap = outputImage .* uint8(mask); % 应用掩码
        % 显示结果
        imshow(maskedHeatmap);
        title([labels{k} '行为时长热力图(s)']);
        clim([min(visitFrequency(:)) max(visitFrequency(:))]); % 设置颜色条的范围
        myjet = jet;
        myjet(1,:) = [1 1 1];
        colormap(myjet);
        colorbar;
    end

%% C3行为发生率
    function behavior_frequency(~,~)
        if isempty(data_store.behavior_data)
            errordlg('请先载入建筑空间行为数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        data=data_store.behavior_data;
        labels = data.behaviortype;
        labels =unique(labels);
        regions = data.Region;
        actions=data.BehaviorNum;
        durations =data.t;
        unique_regions = unique(regions);
        unique_actions = unique(actions);
        duration_matrix = zeros(length(unique_regions), length(unique_actions));
        for i = 1:length(unique_regions)
            for j = 1:length(unique_actions)
                region_mask = (regions == unique_regions(i));
                action_mask = (actions == unique_actions(j));
                duration_matrix(i, j) = sum(durations(region_mask & action_mask))/sum(durations(region_mask));
            end
        end
        % 写入Excel文件
        data_table = table(unique_regions, duration_matrix);
        writetable(data_table, 'C3行为发生率.xlsx');
        bar(ax,unique_regions, duration_matrix, 'stacked');
        title(ax,'区域中各行为发生率');
        legend(ax,labels, 'Location', 'best');
        % 输入行为编号
        while true
            k = inputdlg('请输入行为编号（1.休闲娱乐 2.吸烟 3.其他）', '行为编号');

            % 检查是否取消输入
            if isempty(k)
                error('用户取消了输入');
            end

            % 转换为数值并验证
            k = str2double(k{1});
            if ~isnan(k) && isreal(k) && k > 0 && rem(k,1) == 0
                break;
            else
                errordlg('输入必须为正确的行为编号！', '输入错误');
            end
        end
        bar(ax1,unique_regions, duration_matrix(:,k), 'stacked');
        title(ax1,[labels{k} '行为发生率']);
    end

%% C4行为符合度
    function behavior_degree(~,~)
        if isempty(data_store.behavior_data)
            errordlg('请先载入建筑空间行为数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        data=data_store.behavior_data;
        users = data.UserID;
        regions = data.Region;
        actions=data.BehaviorNum;
        durations =data.t;
        unique_regions = unique(regions);
        unique_users = unique(users);
        unique_actions = unique(actions);
        duration_matrix = zeros(length(unique_regions), length(unique_actions));
        duration_users = zeros(length(unique_users), length(unique_actions));
        for i = 1:length(unique_regions)
            for j = 1:length(unique_actions)
                region_mask = (regions == unique_regions(i));
                action_mask = (actions == unique_actions(j));
                duration_matrix(i, j) = sum(durations(region_mask & action_mask))/sum(durations(region_mask));
            end
        end
        for i = 1:length(unique_users)
            for j = 1:length(unique_actions)
                user_mask = (users == unique_users(i));
                action_mask = (actions == unique_actions(j));
                duration_users(i, j) = sum(durations(user_mask & action_mask))/sum(durations(region_mask));
            end
        end
        entropy_values = zeros(length(unique_regions), 1); % 存储熵值
        entropy_users = zeros(length(unique_users), 1);
        for i = 1:length(unique_regions)
            probs = duration_matrix(i, :); % 当前区域的所有概率
            probs = probs(probs > 0); % 去除 0 概率（避免 log(0) 报错）
            entropy_values(i) = -sum(probs .* log2(probs)); % 计算熵
        end
        for i = 1:length(unique_users)
            probs = duration_users(i, :); % 当前区域的所有概率
            probs = probs(probs > 0); % 去除 0 概率（避免 log(0) 报错）
            entropy_users(i) = -sum(probs .* log2(probs)); % 计算熵
        end
        % 写入Excel文件
        data_table = table(unique_regions, entropy_values, 'VariableNames', {'区域编号', '行为复合度'});
        writetable(data_table, 'C4行为复合程度.xlsx');
        bar(ax,unique_regions, entropy_values);
        title(ax,'各区域行为复合程度');
        bar(ax1,unique_users, entropy_users);
        title(ax1,'使用者行为复合程度');
    end

%% C5功能利用率
    function space_utilization(~,~)
        if isempty(data_store.behavior_data)
            errordlg('请先载入建筑空间行为数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        ra=18.06; %图像与实际尺寸比例
        data=data_store.behavior_data;
        regions = data.Region;
        actions=data.BehaviorNum;
        durations =data.t;
        labels=unique(data.behaviortype);
        unique_regions = unique(regions);
        unique_actions = unique(actions);
        count_matrix = zeros(length(unique_regions), length(unique_actions));
        duration_matrix = zeros(length(unique_regions), length(unique_actions));
        for i = 1:length(unique_regions)
            for j = 1:length(unique_actions)
                region_mask = (regions == unique_regions(i));
                action_mask = (actions == unique_actions(j));
                count_matrix(i, j) = sum(region_mask & action_mask);
                duration_matrix(i, j) = sum(durations(region_mask & action_mask));
            end
        end

        %% 计算各区域面积
        % 1. 读取数据
        data = readtable('region_coordinates.xlsx');

        % 2. 提取唯一区域编号
        regionIDs = unique(data{:, 1}); % 第一列是区域编号

        % 3. 初始化存储面积的数组
        regionAreas = zeros(length(regionIDs), 2); % [区域编号, 面积]

        % 4. 遍历每个区域，计算面积
        for i = 1:length(regionIDs)
            id = regionIDs(i);

            % 提取当前区域的坐标
            regionData = data(data{:, 1} == id, :); % 筛选当前区域的数据
            x = regionData{:, 2}; % 第二列是 x 坐标
            y = regionData{:, 3}; % 第三列是 y 坐标

            % 确保多边形闭合（首尾顶点相同）
            if x(1) ~= x(end) || y(1) ~= y(end)
                x = [x; x(1)];
                y = [y; y(1)];
            end

            % 计算面积（使用鞋带公式）
            area = 0.5 * abs(sum(x(1:end-1) .* y(2:end)) - sum(y(1:end-1) .* x(2:end)));
            % area = polyarea(x, y);
            % 存储结果
            regionAreas(i, :) = [id, area];
        end
        regionAreas=regionAreas(:,2)/ra/ra;  % 区域实际面积
        regionAreas=[regionAreas([1,3:end])]; % 删除区域2
        region_counts1=duration_matrix./regionAreas;
        % 写入Excel文件
        data_table = table(unique_regions, region_counts1, 'VariableNames', {'区域编号', '空间功能利用率'});
        writetable(data_table, 'C5空间功能利用率.xlsx');
        %显示结果
        bar(ax,unique_regions, region_counts1, 'stacked');
        title(ax,'空间空能利用率(s/㎡)');
        legend(ax,labels, 'Location', 'best');
        % 输入行为编号
        while true
            k = inputdlg('请输入行为编号（1.休闲娱乐 2.吸烟 3.其他）', '行为编号');

            % 检查是否取消输入
            if isempty(k)
                error('用户取消了输入');
            end

            % 转换为数值并验证
            k = str2double(k{1});
            if ~isnan(k) && isreal(k) && k > 0 && rem(k,1) == 0
                break;
            else
                errordlg('输入必须为正确的行为编号！', '输入错误');
            end
        end
        bar(ax1,unique_regions, duration_matrix(:,k)./regionAreas);
        title(ax1,[labels{k} '功能利用率(s/㎡)']);

        % 添加标准线
        totalNum=sum(duration_matrix(:,k));
        tatalAre=sum(regionAreas(1:end-1)); 
        stander=totalNum/tatalAre;
        yline(ax1,stander, 'r--', '整个空间该行为的功能利用率', 'LineWidth', 2, 'LabelVerticalAlignment', 'bottom');
    end

%% D3整体满意度
    function satisfaction(~,~)
        if isempty(data_store.ques_data)
            errordlg('请先载入问卷数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        data=data_store.ques_data;
        userIDs =data.UserNum;
        satisfy_num=data.Satisfaction;

        % 写入Excel文件
        data_table = table(userIDs, satisfy_num, 'VariableNames', {'人员编号', '整体满意度'});
        writetable(data_table, 'D3空间整体满意度.xlsx');
        %显示结果
        bar(ax,userIDs,satisfy_num);
        xlabel(ax,'人员编号');       % 调整轴标签
        ylabel(ax,'满意度得分');
        title(ax,'空间整体满意度');
        % 添加标准线
        stander=mean(satisfy_num);
        yline(ax,stander, 'r--', '空间满意度平均得分', 'LineWidth', 2, 'LabelVerticalAlignment', 'bottom');
 end

%% D4空间满意度
    function satisfaction_region(~,~)
        if isempty(data_store.ques_data)
            errordlg('请先载入问卷数据！');
            return;
        end
        cla(ax, 'reset')
        cla(ax1, 'reset')
        data=table2array(data_store.ques_data(:,3:end));
        regionIDs = [1 3 4 5 6 7 8 9]'; % 第一列是区域编号
        avgSatisfaction = mean(data, 1)'; 
        % 写入Excel文件
        writematrix(avgSatisfaction, 'D41空间区域满意度.xlsx');
        writematrix(regionIDs, 'D42空间区域满意度.xlsx');
        data_table = table(regionIDs,avgSatisfaction, 'VariableNames', {'区域编号', '区域满意度'});
        writetable(data_table, 'D4空间区域满意度.xlsx');
        %显示结果
        bar(ax,regionIDs, avgSatisfaction);
        xlabel(ax,'区域编号');       % 调整轴标签
        ylabel(ax,'满意度得分');
        title(ax,'区域满意度');
        % 添加标准线
        stander=mean(avgSatisfaction);
        yline(ax,stander, 'r--', '区域满意度平均得分', 'LineWidth', 2, 'LabelVerticalAlignment', 'bottom');
 end


     %%  清除,保存功能模块
    function clear_current_view(~,~)

        % 重置坐标轴
        cla(ax, 'reset')
        cla(ax1, 'reset')
    end

    function save_current_view(~,~)
        [file, path] = uiputfile(...
            {'*.png','PNG图像'; '*.pdf','PDF文档'; '*.jpg','JPEG图像'},...
            '保存当前视图');

        if ~isequal(file,0)
            try
                exportgraphics(ax, fullfile(path,file),...
                    'Resolution',300,...
                    'BackgroundColor','white');
                msgbox('视图保存成功！');
            catch
                errordlg('保存失败，请检查文件路径和权限！');
            end
        end
    end

    function export_all_data(~,~)
        [file, path] = uiputfile(...
            {'*.xlsx','Excel文件'; '*.csv','CSV文件'},...
            '选择保存位置',...
            'analysis_results.xlsx');

        if ~isequal(file,0)
            try
                % 保存热力图数据
                if isfield(data_store.results, 'heatmap')
                    writematrix(data_store.results.heatmap,...
                        fullfile(path,file), 'Sheet','热力图矩阵');
                end

                % 保存原始数据
                if ~isempty(data_store.loc_data)
                    writetable(data_store.loc_data,...
                        fullfile(path,file), 'Sheet','定位数据');
                end

                % 保存其他分析结果...

                msgbox('数据导出成功！');
            catch ME
                errordlg(['导出失败：' ME.message]);
            end
        end
    end

    function data = loadDataFile(fullpath)
        [~,~,ext] = fileparts(fullpath);
        if strcmpi(ext, '.csv') || strcmpi(ext, '.xlsx')
            data = readtable(fullpath);
        elseif strcmpi(ext, '.mat')
            data = load(fullpath);
            data = struct2table(data);
        else
            error('不支持的文件格式');
        end
    end
end